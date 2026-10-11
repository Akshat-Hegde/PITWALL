"""Staff page (/staff) and its API: sessions per rig (with booking timers), driver profiles, the queue.

With [staff] pin set, every /api/staff call needs the header X-Staff-Pin. Repeated wrong PINs from one
address lock that address out for a minute.
"""

from __future__ import annotations

import hmac
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from ..core.drivers import EXTEND_PROMPT_MS, DriverError
from ..core.feed import FeedBuilder, lan_address
from ..core.health import RigState

if TYPE_CHECKING:
    from ..hub import Hub

PIN_HEADER = "X-Staff-Pin"
MAX_FAILURES = 5
FAILURE_WINDOW_S = 60.0

STAFF_PAGE = Path(__file__).with_name("staff.html")
STATE_TEXT = {RigState.DRIVING: "On track", RigState.IN_MENU: "In menu", RigState.NO_DATA: "No data"}


class PinGuard:
    def __init__(self, pin: str, clock=time.monotonic, header: str = PIN_HEADER) -> None:
        self.pin = pin
        self.header = header
        self._clock = clock
        self._failures: dict[str, deque[float]] = defaultdict(deque)

    def __call__(self, request: Request) -> None:
        if not self.pin:
            return
        client = request.client.host if request.client else "?"
        now = self._clock()
        failures = self._failures[client]
        while failures and now - failures[0] > FAILURE_WINDOW_S:
            failures.popleft()
        if len(failures) >= MAX_FAILURES:
            raise HTTPException(429, "Too many wrong PINs. Wait a minute, then try again.")
        given = request.headers.get(self.header, "")
        if not hmac.compare_digest(given.encode(), self.pin.encode()):
            if given:
                failures.append(now)
            raise HTTPException(401, "Wrong PIN." if given else "Enter the staff PIN.")


def _bad(exc: DriverError) -> HTTPException:
    return HTTPException(400, str(exc))


def staff_router(hub: Hub) -> APIRouter:
    router = APIRouter()
    guard = PinGuard(hub.config.staff.pin)
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
            "state_text": STATE_TEXT[state],
            "track_name": s.track if s and state is not RigState.NO_DATA else None,
            "game_driver": rig.driver_name,
            "session": assigned.to_json() if assigned else None,
            "time_left_ms": left,
            "extend_prompt": left is not None and left <= EXTEND_PROMPT_MS,
            "laps_stored_as": drivers.lap_name(rig.ip, rig.driver_name, rig.name),
        }

    def find_rig(rig_id: str):
        rig = hub.registry.get(rig_id)
        if rig is None:
            raise HTTPException(404, "No rig with that ID. Reload the page.")
        return rig

    @router.get("/staff", response_class=HTMLResponse, include_in_schema=False)
    def page() -> str:
        return STAFF_PAGE.read_text(encoding="utf-8")

    @router.get("/api/staff/rigs", dependencies=[Depends(guard)])
    def rigs() -> dict[str, Any]:
        now = time.monotonic()
        return {"cafe": hub.config.cafe.name, "rigs": [rig_row(r, now) for r in hub.registry.all()],
                "queue": drivers.queue(), "features": hub.config.features.model_dump(), "demo": hub.demo is not None}

    status_builder = FeedBuilder(hub)

    @router.get("/api/staff/health", dependencies=[Depends(guard)])
    def health() -> dict[str, Any]:
        """Technical diagnostics for staff only (addresses, warnings, packet rates). The TV never shows these."""
        now = time.monotonic()
        snapshot = hub.health_snapshot()
        warnings = list(status_builder.status(now)["warnings"])
        for rig in snapshot["rigs"]:
            if rig["state"] == RigState.NO_DATA.value:
                warnings.append({"code": "no_data", "rig_id": rig["ip"],
                                 "message": f"Nothing from {rig['name']} ({rig['ip']}). In F1 25 turn UDP telemetry "
                                            f"on and drive out in Time Trial."})
        return {"warnings": warnings, "rigs": snapshot["rigs"], "uptime_s": snapshot["uptime_s"],
                "recorder": snapshot.get("recorder"),
                "target": {"address": lan_address(), "port": hub.config.network.udp_port}}

    @router.post("/api/staff/demo/{action}", dependencies=[Depends(guard)])
    def demo(action: str, body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
        """Demo director (run --demo only): trigger a moment on demand."""
        if hub.demo is None:
            raise HTTPException(404, "The demo director only exists in demo mode (run --demo).")
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
        card = hub.end_session(rig.ip)
        return {**rig_row(rig, time.monotonic()), "card": _card_link(card)}

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
        details = drivers.profile_details(driver_id, hub.config.leaderboard.day_start_hour)
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


def _card_link(card: dict[str, Any] | None) -> dict[str, Any] | None:
    return {"token": card["token"], "url": card["url"], "driver": card["driver"]} if card else None


def _colour(rig) -> str:
    from ..core.feed import rig_colour
    return rig_colour(rig)
