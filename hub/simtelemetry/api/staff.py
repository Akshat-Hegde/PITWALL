"""Staff page (/staff) and its API: set or clear the current driver's name per rig.

With [staff] pin set, every /api/staff call needs the header X-Staff-Pin. Repeated wrong PINs
from one address lock that address out for a minute.
"""

from __future__ import annotations

import hmac
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from ..core.drivers import DriverError
from ..core.health import RigState

if TYPE_CHECKING:
    from ..hub import Hub

PIN_HEADER = "X-Staff-Pin"
MAX_FAILURES = 5
FAILURE_WINDOW_S = 60.0

STAFF_PAGE = Path(__file__).with_name("staff.html")
STATE_TEXT = {RigState.DRIVING: "On track", RigState.IN_MENU: "In menu", RigState.NO_DATA: "No data"}


class PinGuard:
    def __init__(self, pin: str, clock=time.monotonic) -> None:
        self.pin = pin
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
        given = request.headers.get(PIN_HEADER, "")
        if not hmac.compare_digest(given.encode(), self.pin.encode()):
            if given:
                failures.append(now)
            raise HTTPException(401, "Wrong PIN." if given else "Enter the staff PIN.")


def staff_router(hub: Hub) -> APIRouter:
    router = APIRouter()
    guard = PinGuard(hub.config.staff.pin)

    def rig_row(rig, now: float) -> dict[str, Any]:
        s = hub.adapter.live_summary(rig.ip)
        state = hub.health.state(rig.ip, now)
        assigned = hub.drivers.get(rig.ip)
        return {
            "rig_id": rig.ip,
            "rig_name": rig.name,
            "colour": _colour(rig),
            "state": state.value,
            "state_text": STATE_TEXT[state],
            "track_name": s.track if s and state is not RigState.NO_DATA else None,
            "game_driver": rig.driver_name,
            "assigned": assigned.to_json() if assigned else None,
            "laps_stored_as": hub.drivers.lap_name(rig.ip, rig.driver_name, rig.name),
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
        return {"cafe": hub.config.cafe.name, "rigs": [rig_row(r, now) for r in hub.registry.all()]}

    @router.put("/api/staff/rigs/{rig_id}/driver", dependencies=[Depends(guard)])
    def assign(rig_id: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        rig = find_rig(rig_id)
        try:
            hub.drivers.assign(rig.ip, body.get("name"), body.get("phone"), body.get("email"))
        except DriverError as exc:
            raise HTTPException(400, str(exc)) from None
        hub.announce_driver(rig.ip)
        return rig_row(rig, time.monotonic())

    @router.delete("/api/staff/rigs/{rig_id}/driver", dependencies=[Depends(guard)])
    def end(rig_id: str) -> dict[str, Any]:
        rig = find_rig(rig_id)
        hub.drivers.end(rig.ip)
        return rig_row(rig, time.monotonic())

    @router.post("/api/staff/podium", dependencies=[Depends(guard)])
    def podium() -> dict[str, Any]:
        moment = hub.podium("staff")
        if moment is None:
            raise HTTPException(409, "Nothing to show yet: no clean laps today on the track the TV shows.")
        return {"shown": True, "entries": len(moment["entries"])}

    return router


def _colour(rig) -> str:
    from ..core.feed import rig_colour
    return rig_colour(rig)
