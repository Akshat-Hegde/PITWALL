"""/setup: first-run setup and branding. Before setup: the one-time setup code. After: the owner PIN.

The setup code is never returned by any endpoint; it lives in the console/log, the installer and `setup-code`.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import ValidationError

from .. import brand
from ..core.feed import lan_address
from ..core.settings import CafeSettings, SettingsStore, apply_settings
from ..core.setup_code import SetupCode, SetupLocked
from .owner import OWNER_PIN_HEADER
from .staff import PinGuard

if TYPE_CHECKING:
    from ..hub import Hub

SETUP_PAGE = Path(__file__).with_name("setup.html")
LOGO_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
MAX_LOGO_BYTES = 1024 * 1024


def setup_router(hub: Hub) -> APIRouter:
    router = APIRouter()
    store = SettingsStore(hub.config.data_dir)
    setup_code = SetupCode(hub.config.data_dir)
    owner_guard = PinGuard(lambda: hub.config.owner.pin, header=OWNER_PIN_HEADER)  # same rate limit as /owner

    def current() -> CafeSettings | None:
        return store.load()

    def guard(request: Request, code: str | None) -> None:
        """Before setup: the one-time setup code. After: the owner PIN."""
        s = current()
        if s is not None and s.setup_done:
            if not request.headers.get(OWNER_PIN_HEADER):
                raise HTTPException(401, "Enter the owner PIN to change the setup.")
            owner_guard(request)
            return
        try:
            ok = setup_code.check(code)
        except SetupLocked as exc:
            raise HTTPException(429, str(exc)) from None
        if not ok:
            raise HTTPException(401, "Enter the setup code from the installer's last page "
                                     "(also in the hub's log, or run: <exe> setup-code).")

    @router.get("/setup")
    def page() -> FileResponse:
        return FileResponse(SETUP_PAGE)

    @router.get("/api/setup")
    def state() -> dict[str, Any]:
        s = current()
        c = hub.config
        return {
            "product": brand.PRODUCT_NAME,
            "setup_done": bool(s and s.setup_done),
            "needs_code": not (s and s.setup_done),
            "name": c.cafe.name, "tagline": c.cafe.tagline, "logo": c.cafe.logo,
            "accent": c.cafe.branding.get("--brand-accent", "#E10600"),
            "open_hour": c.owner.open_hour, "close_hour": c.owner.close_hour,
            "hub_address": lan_address(), "http_port": c.network.http_port, "udp_port": c.network.udp_port,
            "rigs": [{"rig_id": r.ip, "name": r.name} for r in hub.registry.all()],
        }

    @router.post("/api/setup")
    def save(request: Request, body: dict[str, Any], x_setup_code: str | None = Header(None)) -> dict[str, Any]:
        guard(request, x_setup_code)
        old = current()
        try:
            s = CafeSettings(**{**body, "logo": old.logo if old else hub.config.cafe.logo, "setup_done": True})
        except ValidationError as exc:
            raise HTTPException(400, "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()))
        store.save(s)
        apply_settings(hub.config, s)
        setup_code.clear()                      # used up: from now on the owner PIN guards /setup
        return state()

    @router.post("/api/setup/logo")
    async def logo(request: Request, file: UploadFile, x_setup_code: str | None = Header(None)) -> dict[str, Any]:
        guard(request, x_setup_code)
        ext = LOGO_TYPES.get(file.content_type or "")
        data = await file.read()
        if ext is None:
            raise HTTPException(400, "Use a PNG, JPEG or WebP image.")
        if len(data) > MAX_LOGO_BYTES:
            raise HTTPException(400, "The logo must be under 1 MB.")
        store.branding_dir.mkdir(parents=True, exist_ok=True)
        name = f"logo-{hashlib.sha256(data).hexdigest()[:8]}{ext}"   # new image = new name = new URL (cache busting)
        for old in store.branding_dir.glob("logo*"):
            old.unlink()
        (store.branding_dir / name).write_bytes(data)
        hub.config.cafe.logo = name
        s = current()
        if s is not None:
            store.save(s.model_copy(update={"logo": hub.config.cafe.logo}))
        return {"logo": hub.config.cafe.logo}

    @router.get("/api/cafe/logo")
    def serve_logo() -> FileResponse:
        name = hub.config.cafe.logo
        path = store.branding_dir / name if name else None
        if path is None or not path.is_file():
            raise HTTPException(404, "No logo")
        return FileResponse(path, headers={"Cache-Control": "no-cache"})

    return router
