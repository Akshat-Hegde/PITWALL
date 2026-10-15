"""Staff page (/staff) and its API: sessions per rig (with booking timers), driver profiles, the queue.

Every /api/staff call needs the header X-Staff-Pin: the staff PIN, or the owner PIN while no staff PIN is set.
A hub with no PIN at all serves no staff data. Repeated wrong PINs lock the address out (core/pins.py).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from ..core.drivers import EXTEND_PROMPT_MS, DriverError, clean_name
from ..core.feed import FeedBuilder
from ..core.tv import TvError
from ..core.wifi import wifi_share
from ..hub import NO_CARD_TEXT
from ..core.health import RigState
from ..core.pins import PinAttempts, verify_pin
from .pages import render_page

if TYPE_CHECKING:
    from ..hub import Hub

PIN_HEADER = "X-Staff-Pin"
NO_PIN_TEXT = "Finish setup first: open the setup page on the hub PC and choose the PINs."

STAFF_PAGE = Path(__file__).with_name("staff.html")
PRINT_PAGE = Path(__file__).with_name("checkin_print.html")


class PinGuard:
    """Checks the PIN header on every request. No PIN set at all is refused (never served open); wrong PINs count
    towards the shared lock-out (core/pins.py PinAttempts)."""

    def __init__(self, pin: Callable[[], str], clock=time.monotonic, header: str = PIN_HEADER,
                 attempts: PinAttempts | None = None, missing: str = NO_PIN_TEXT) -> None:
        self._pin = pin  # read on every request, so a PIN changed from /setup applies at once
        self.header = header
        self.attempts = attempts if attempts is not None else PinAttempts(clock)
        self.missing = missing

    def __call__(self, request: Request) -> None:
        pin = self._pin()
        if not pin:
            raise HTTPException(403, self.missing)
        client = request.client.host if request.client else "?"
        locked = self.attempts.locked(client)
        if locked:
            raise HTTPException(429, locked)
        given = request.headers.get(self.header, "")
        if not verify_pin(given, pin):
            if given:
                self.attempts.failed(client)
            raise HTTPException(401, "Wrong PIN." if given else "Enter the staff PIN.")


def _bad(exc: DriverError) -> HTTPException:
    return HTTPException(400, str(exc))


def staff_router(hub: Hub) -> APIRouter:
    router = APIRouter()
    # Until a staff PIN is set (installs from before it was required), the owner PIN opens the staff page.
    guard = PinGuard(lambda: hub.config.staff.pin or hub.config.owner.pin, attempts=hub.pin_attempts)
    drivers = hub.drivers

    def rig_row(rig, now: float) -> dict[str, Any]:
        s = hub.adapter.live_summary(rig.ip)
        state = hub.health.state(rig.ip, now)
        assigned = drivers.get(rig.ip)
        left = drivers.time_left_ms(rig.ip)
        return {
            "rig_id": rig.ip,
            "rig_name": rig.name,
            "colour": _colour(rig),
            "state": state.value,
            "state_text": hub.state_text(rig.ip, now),
            "track_name": s.track if s and state is not RigState.NO_DATA else None,
            "game_driver": rig.driver_name,
            "session": assigned.to_json() if assigned else None,
            "time_left_ms": left,
            "extend_prompt": left is not None and left <= EXTEND_PROMPT_MS,
            "laps_stored_as": drivers.lap_name(rig.ip, rig.driver_name, rig.name),
            # The last session here ended by itself (closing time, time up): until the next session starts.
            "auto_ended": hub.auto_ended.get(rig.ip) if assigned is None else None,
        }

    def find_rig(rig_id: str):
        rig = hub.registry.get(rig_id)
        if rig is None:
            raise HTTPException(404, "No rig with that ID. Reload the page.")
        return rig

    @router.get("/staff", response_class=HTMLResponse, include_in_schema=False)
    def page() -> HTMLResponse:
        return render_page(STAFF_PAGE)

    @router.get("/staff/checkin-print", response_class=HTMLResponse, include_in_schema=False)
    def checkin_print_page() -> HTMLResponse:
        return render_page(PRINT_PAGE)       # the page asks for the PIN itself, like /staff

    @router.get("/api/staff/rigs", dependencies=[Depends(guard)])
    def rigs() -> dict[str, Any]:
        now = time.monotonic()
        return {"cafe": hub.config.cafe.name, "rigs": [rig_row(r, now) for r in hub.registry.all()],
                "queue": drivers.queue(), "features": hub.config.features.model_dump(), "demo": hub.demo is not None,
                # Unlocked with the owner PIN because no staff PIN is set: the page shows a red banner.
                "staff_pin_missing": not hub.config.staff.pin}

    status_builder = FeedBuilder(hub)

    @router.get("/api/staff/health", dependencies=[Depends(guard)])
    def health() -> dict[str, Any]:
        """Technical diagnostics for staff only (addresses, warnings, packet rates). The TV never shows these."""
        now = time.monotonic()
        snapshot = hub.health_snapshot()
        warnings = (hub.admin_warnings() + list(status_builder.status(now)["warnings"])
                    + hub.wrong_sender_warnings(now) + hub.silent_rig_warnings(now))
        return {"warnings": warnings, "rigs": snapshot["rigs"], "uptime_s": snapshot["uptime_s"],
                "recorder": snapshot.get("recorder"),
                "target": {"address": hub.hub_address(), "port": hub.config.network.udp_port}}

    @router.post("/api/staff/address/ok", dependencies=[Depends(guard)])
    async def address_ok() -> dict[str, Any]:
        """"OK, done" on the address-change warning: every rig and the stickers now use the new address."""
        return {"address": hub.address_watch.acknowledge()}

    @router.get("/api/staff/tv", dependencies=[Depends(guard)])
    def tv() -> dict[str, Any]:
        return hub.tv.to_json()

    @router.put("/api/staff/tv", dependencies=[Depends(guard)])
    def set_tv(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        """{"page": "live" | "multi"}, {"pinned_rig": rig_id | null}, {"overlay": "head_to_head" | "teams" | null}."""
        fields = {k: body[k] for k in ("page", "pinned_rig", "overlay") if k in body}
        if fields.get("pinned_rig"):
            find_rig(str(fields["pinned_rig"]))
        if fields.get("overlay") == "head_to_head" and not hub.config.features.head_to_head:
            raise HTTPException(400, "Head to head is switched off on this hub.")
        if fields.get("overlay") == "teams" and not hub.config.features.events:
            raise HTTPException(400, "Corporate events are switched off on this hub.")
        try:
            return hub.tv.set(**fields)
        except TvError as exc:
            raise HTTPException(400, str(exc)) from None

    @router.post("/api/staff/demo/{action}", dependencies=[Depends(guard)])
    async def demo(action: str, body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
        """Demo director (run --demo only): trigger a moment on demand. async so it runs on the event loop,
        the only place the RaceBook is touched."""
        if hub.demo is None:
            raise HTTPException(404, "The demo director only works when the hub runs in demo mode.")
        try:
            return hub.demo.run(action, body)
        except DriverError as exc:
            raise _bad(exc) from None

    # --- sessions ----------------------------------------------------------------------------

    @router.put("/api/staff/rigs/{rig_id}/driver", dependencies=[Depends(guard)])
    def start(rig_id: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        """Start a session: {"name"} for a walk-in or {"driver_id"} for a profile, optional "minutes"."""
        rig = find_rig(rig_id)
        previous = drivers.get(rig.ip)  # replaced by the new session once that is valid
        try:
            if body.get("queue_id") is not None:
                drivers.start_from_queue(int(body["queue_id"]), rig.ip, body.get("minutes"))
            else:
                drivers.assign(rig.ip, body.get("name"), body.get("driver_id"), body.get("minutes"))
        except DriverError as exc:
            raise _bad(exc) from None
        card = hub.session_card(rig.ip, previous) if previous else None
        hub.session_started(rig.ip)
        return {**rig_row(rig, time.monotonic()), "card": _card_link(card)}

    @router.get("/api/staff/names/check", dependencies=[Depends(guard)])
    def name_check(name: str = "", rig_id: str = "") -> dict[str, Any]:
        """Before starting a walk-in name: is it already driving on another rig or on today's board? The page then
        asks "There's already an Alex today. Same person?" (same name = one line on the boards)."""
        try:
            clean = clean_name(name)
        except DriverError as exc:
            raise _bad(exc) from None
        where = hub.name_in_use(clean, rig_id or None)
        return {"name": clean, "in_use": where is not None, "where": where}

    @router.get("/api/staff/wifi", dependencies=[Depends(guard)])
    def wifi() -> dict[str, Any]:
        """The guest Wi-Fi QR for the card panel ("Join the Wi-Fi first"), or null when none is set."""
        share = wifi_share(hub.config)
        return {"wifi": {"ssid": share["ssid"], "svg": _qr_svg(share["qr"])} if share else None}

    @router.post("/api/staff/rigs/{rig_id}/extend", dependencies=[Depends(guard)])
    def extend(rig_id: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        rig = find_rig(rig_id)
        try:
            drivers.extend(rig.ip, body.get("minutes"))
        except DriverError as exc:
            raise _bad(exc) from None
        return rig_row(rig, time.monotonic())

    @router.delete("/api/staff/rigs/{rig_id}/driver", dependencies=[Depends(guard)])
    def end(rig_id: str) -> dict[str, Any]:
        rig = find_rig(rig_id)
        had_session = drivers.get(rig.ip) is not None
        card = hub.end_session(rig.ip)
        hub.auto_ended.pop(rig.ip, None)
        note = NO_CARD_TEXT if had_session and card is None and hub.config.features.sharing else None
        return {**rig_row(rig, time.monotonic()), "card": _card_link(card), "card_note": note}

    # --- self check-in codes -------------------------------------------------------------------

    def code_row(rig, code: str) -> dict[str, Any]:
        address = hub.hub_address() or "localhost"
        return {"rig_id": rig.ip, "rig_name": rig.name, "code": code,
                "url": f"http://{address}:{hub.config.network.http_port}/checkin/{code}"}

    @router.get("/api/staff/checkin/codes", dependencies=[Depends(guard)])
    def checkin_codes() -> dict[str, Any]:
        codes = hub.checkin.codes()
        return {"enabled": hub.config.features.self_checkin,
                "rigs": [code_row(r, codes[r.ip]) for r in hub.registry.all() if r.ip in codes]}

    @router.get("/api/staff/checkin/sheet", dependencies=[Depends(guard)])
    def checkin_sheet() -> dict[str, Any]:
        """Everything the printable sticker sheet needs: a QR (inline SVG) per rig, and the guest Wi-Fi QR if set."""
        codes = hub.checkin.codes()
        rigs = [{**row, "svg": _qr_svg(row["url"])}
                for row in (code_row(r, codes[r.ip]) for r in hub.registry.all() if r.ip in codes)]
        share = wifi_share(hub.config)
        return {"enabled": hub.config.features.self_checkin, "rigs": rigs,
                "wifi": {"ssid": share["ssid"], "svg": _qr_svg(share["qr"])} if share else None}

    @router.post("/api/staff/checkin/codes/{rig_id}/regenerate", dependencies=[Depends(guard)])
    def checkin_regenerate(rig_id: str) -> dict[str, Any]:
        """A new code for one rig: the sticker with the old code stops working."""
        rig = find_rig(rig_id)
        return code_row(rig, hub.checkin.regenerate(rig.ip))

    # --- driver profiles -----------------------------------------------------------------------

    @router.get("/api/staff/drivers", dependencies=[Depends(guard)])
    def search(q: str = "", phone: str = "") -> dict[str, Any]:
        """Search profiles by name or phone (?q=; ?phone= still works)."""
        try:
            return {"drivers": drivers.search(q or phone)}
        except DriverError as exc:
            raise _bad(exc) from None

    @router.post("/api/staff/drivers/quick", dependencies=[Depends(guard)])
    def quick(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        """Quick profile: a name only, for walk-ins at events."""
        try:
            return drivers.create_quick_profile(body.get("name"))
        except DriverError as exc:
            raise _bad(exc) from None

    @router.post("/api/staff/drivers", dependencies=[Depends(guard)])
    def create(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        try:
            return drivers.create_profile(body.get("name"), body.get("phone"), body.get("consent"))
        except DriverError as exc:
            raise _bad(exc) from None

    @router.get("/api/staff/drivers/{driver_id}", dependencies=[Depends(guard)])
    def profile(driver_id: int) -> dict[str, Any]:
        details = drivers.profile_details(driver_id, hub.config.day_start_hour)
        if details is None:
            raise HTTPException(404, "That driver profile doesn't exist.")
        return details

    @router.delete("/api/staff/drivers/{driver_id}", dependencies=[Depends(guard)])
    def delete(driver_id: int) -> dict[str, Any]:
        try:
            removed = drivers.delete_profile(driver_id)
        except DriverError as exc:
            raise HTTPException(404, str(exc)) from None
        hub.laps.forget_driver(driver_id)
        return {"deleted": True, **removed}

    # --- queue -------------------------------------------------------------------------------

    @router.post("/api/staff/queue", dependencies=[Depends(guard)])
    def queue_add(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        try:
            drivers.queue_add(body.get("name"), body.get("driver_id"))
        except DriverError as exc:
            raise _bad(exc) from None
        return {"queue": drivers.queue()}

    @router.delete("/api/staff/queue/{entry_id}", dependencies=[Depends(guard)])
    def queue_remove(entry_id: int) -> dict[str, Any]:
        drivers.queue_remove(entry_id)
        return {"queue": drivers.queue()}

    # --- competitions --------------------------------------------------------------------------

    comp = hub.competitions

    def guarded(fn, *args):
        try:
            return fn(*args)
        except DriverError as exc:
            raise _bad(exc) from None

    @router.get("/api/staff/competitions", dependencies=[Depends(guard)])
    def competitions() -> dict[str, Any]:
        return {"tracks": hub.drivers.store.tracks(), "challenges": comp.challenges(),
                "event": comp.active_event(hub.active_track()), "features": hub.config.features.model_dump()}

    @router.post("/api/staff/challenges", dependencies=[Depends(guard)])
    def challenge_create(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        return guarded(comp.create_challenge, body)

    @router.delete("/api/staff/challenges/{challenge_id}", dependencies=[Depends(guard)])
    def challenge_delete(challenge_id: int) -> dict[str, Any]:
        return {"deleted": comp.delete_challenge(challenge_id)}

    @router.post("/api/staff/events", dependencies=[Depends(guard)])
    def event_create(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        return guarded(comp.create_event, body)

    @router.post("/api/staff/events/{event_id}/end", dependencies=[Depends(guard)])
    def event_end(event_id: int) -> dict[str, Any]:
        comp.end_event(event_id)
        return {"ended": True}

    @router.post("/api/staff/events/{event_id}/logo", dependencies=[Depends(guard)])
    def event_logo(event_id: int, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        return {"logo": guarded(comp.save_logo, "event", event_id, body.get("data_url"))}

    @router.post("/api/staff/events/{event_id}/teams", dependencies=[Depends(guard)])
    def team_add(event_id: int, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        return guarded(comp.add_team, event_id, body.get("name"))

    @router.delete("/api/staff/teams/{team_id}", dependencies=[Depends(guard)])
    def team_remove(team_id: int) -> dict[str, Any]:
        comp.remove_team(team_id)
        return {"deleted": True}

    @router.post("/api/staff/teams/{team_id}/logo", dependencies=[Depends(guard)])
    def team_logo(team_id: int, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        return {"logo": guarded(comp.save_logo, "team", team_id, body.get("data_url"))}

    @router.post("/api/staff/teams/{team_id}/members", dependencies=[Depends(guard)])
    def member_add(team_id: int, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        return guarded(comp.add_member, team_id, body.get("driver_id"))

    @router.delete("/api/staff/members/{member_id}", dependencies=[Depends(guard)])
    def member_remove(member_id: int) -> dict[str, Any]:
        comp.remove_member(member_id)
        return {"deleted": True}

    # --- TV ----------------------------------------------------------------------------------

    @router.post("/api/staff/podium", dependencies=[Depends(guard)])
    def podium() -> dict[str, Any]:
        moment = hub.podium("staff")
        if moment is None:
            raise HTTPException(409, "Nothing to show yet: no clean laps today on the track the TV shows.")
        return {"shown": True, "entries": len(moment["entries"])}

    return router


def _qr_svg(text: str) -> str:
    import io

    import segno
    out = io.BytesIO()
    segno.make(text, error="m").save(out, kind="svg", scale=8, border=1, dark="#000", light="#fff", xmldecl=False)
    return out.getvalue().decode("utf-8")


def _card_link(card: dict[str, Any] | None) -> dict[str, Any] | None:
    return {"token": card["token"], "url": card["url"], "driver": card["driver"]} if card else None


def _colour(rig) -> str:
    from ..core.feed import rig_colour
    return rig_colour(rig)
