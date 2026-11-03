"""Self check-in: /checkin/<code> (phone page) and /api/checkin/<code> (JSON). Guests scan a QR sticker on the rig,
type a first name and drive; "I'm done" ends the session and gives their story card.

Everything here needs [features] self_checkin; with it off the API says 403 and the page says to ask staff.
"""

from __future__ import annotations

import html
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import HTMLResponse

from .. import brand
from ..core.drivers import DriverError, clean_name
from ..core.names import is_blocked
from .pages import render_page

if TYPE_CHECKING:
    from ..hub import Hub

CHECKIN_PAGE = Path(__file__).with_name("checkin.html")
BAD_NAME = "Please choose another name."

FRIENDLY = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{{PRODUCT_NAME}}</title></head>
<body style="font-family:system-ui,sans-serif;background:#10161c;color:#eef3f6;margin:0;padding:2rem 16px;text-align:center">
<h1 style="font-size:1.4rem">{message}</h1></body></html>"""


def _friendly(message: str, status: int) -> HTMLResponse:
    page = FRIENDLY.replace("{message}", html.escape(message)).replace("{{PRODUCT_NAME}}", brand.PRODUCT_NAME)
    return HTMLResponse(page, status_code=status)


def checkin_router(hub: Hub) -> APIRouter:
    router = APIRouter()
    svc = hub.checkin
    drivers = hub.drivers

    def require_on() -> None:
        if not hub.features.self_checkin:
            raise HTTPException(403, "Check-in is switched off, please ask staff.")

    def rig_of(code: str):
        rig_id = svc.rig_for(code)
        if rig_id is None:
            raise HTTPException(404, "This code is no longer valid, please ask staff.")
        return hub.registry.get(rig_id)

    @router.get("/checkin/{code}", response_class=HTMLResponse, include_in_schema=False)
    def page(code: str) -> HTMLResponse:
        if not hub.features.self_checkin:
            return _friendly("Check-in is switched off, please ask staff.", 403)
        if svc.rig_for(code) is None:
            return _friendly("This code is no longer valid, please ask staff.", 404)
        return render_page(CHECKIN_PAGE)

    @router.get("/api/checkin/{code}")
    def status(code: str, secret: str | None = None) -> dict[str, Any]:
        require_on()
        rig = rig_of(code)
        base = {"rig_name": rig.name}
        rec = svc.lookup(rig.ip, secret)
        if rec is not None:
            laps = svc.laps(rec)
            yours = svc.is_current(rec)
            out: dict[str, Any] = {**base, "state": "yours" if yours else "ended", "driver": rec.name,
                                   "laps": len(laps)}
            if laps:
                out["best_ms"] = min(r.lap_ms for r in laps)
            if not yours and rec.card_url:
                out["card_url"] = rec.card_url
            return out
        current = drivers.get(rig.ip)
        if current is None:
            return {**base, "state": "free", "laps": 0}
        # an idle check-in session can be taken over: show the name form (no driver name either way)
        return {**base, "state": "idle" if svc.can_take_over(rig.ip, current) else "busy", "laps": 0}

    @router.post("/api/checkin/{code}")
    def check_in(code: str, request: Request, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        require_on()
        if not svc.allow(request.client.host if request.client else "?"):
            raise HTTPException(429, "Too many tries. Wait a minute, then try again.")
        rig = rig_of(code)
        try:
            name = clean_name(body.get("name"))
        except DriverError as exc:
            raise HTTPException(400, str(exc)) from None
        if is_blocked(name, hub.config.checkin.blocked_words):
            raise HTTPException(400, BAD_NAME)
        with svc.lock:                              # two phones at once must not both get the rig
            current = drivers.get(rig.ip)
            if current is not None:
                if not svc.can_take_over(rig.ip, current):
                    raise HTTPException(409, f"{rig.name} is in use. Please ask staff.")
                hub.end_session(rig.ip)             # the previous driver still gets their card
                svc.mark_ended(rig.ip, current.started_at)
            session = drivers.assign(rig.ip, name)  # same start as staff: "Now driving" and the feed follow
            hub.session_started(rig.ip)
            secret = svc.register(rig.ip, session)
        return {"rig_name": rig.name, "driver": session.name, "secret": secret,
                "status_url": f"/api/checkin/{code}?secret={secret}"}

    @router.post("/api/checkin/{code}/done")
    def done(code: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        require_on()
        rig = rig_of(code)
        rec = svc.lookup(rig.ip, str(body.get("secret") or ""))
        if rec is None or not svc.is_current(rec):
            raise HTTPException(403, "This isn't your session any more.")
        with svc.lock:
            if not svc.is_current(rec):
                raise HTTPException(403, "This isn't your session any more.")
            card = hub.end_session(rig.ip)
            svc.mark_ended(rig.ip, rec.started_at)
        return {"card_url": card["url"] if card else None}

    return router
