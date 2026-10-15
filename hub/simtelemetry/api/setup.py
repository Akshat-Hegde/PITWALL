"""/setup: first-run setup and branding. Before setup: the one-time setup code. After: the owner PIN.

The setup code is never returned by any endpoint; it lives in the console/log, the installer and `setup-code`.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING, Any

import time

from fastapi import APIRouter, Body, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import ValidationError

from .. import brand
from ..core.feed import rig_colour
from ..core.pins import is_hashed
from ..core.rigs import RigError
from ..core.settings import CafeSettings, SettingsStore, apply_settings
from ..core.setup_code import SetupCode, SetupLocked
from .owner import OWNER_PIN_HEADER
from .pages import render_page
from .staff import PinGuard

if TYPE_CHECKING:
    from ..hub import Hub

SETUP_PAGE = Path(__file__).with_name("setup.html")
LOGO_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
MAX_LOGO_BYTES = 1024 * 1024


_FIELDS = {"name": "Cafe name", "tagline": "Tagline", "accent": "Accent colour", "owner_pin": "Owner PIN",
           "staff_pin": "Staff PIN", "open_hour": "Opening time", "close_hour": "Closing time",
           "wifi_ssid": "Wi-Fi name", "wifi_password": "Wi-Fi password", "wifi_security": "Wi-Fi security"}


def _plain_errors(exc: ValidationError) -> str:
    """The form's mistakes in plain words: "Staff PIN: PINs are 4 to 8 digits"."""
    out = []
    for e in exc.errors():
        msg = str(e["msg"]).removeprefix("Value error, ")
        field = _FIELDS.get(str(e["loc"][0])) if e["loc"] else None
        out.append(f"{field}: {msg}" if field else msg[:1].upper() + msg[1:])
    return "; ".join(out)


def setup_router(hub: Hub) -> APIRouter:
    router = APIRouter()
    store = SettingsStore(hub.config.data_dir)
    setup_code = SetupCode(hub.config.data_dir)
    owner_guard = PinGuard(lambda: hub.config.owner.pin, header=OWNER_PIN_HEADER,      # same lock-out as /owner
                           attempts=hub.pin_attempts)

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
    def page() -> HTMLResponse:
        return render_page(SETUP_PAGE)

    def authed(request: Request, code: str | None) -> bool:
        """Whether a read comes from the owner (or, before setup, from whoever has the setup code). Only a
        request that sends a PIN or code is checked, so wrong ones still count towards the lock-out."""
        s = current()
        if s is not None and s.setup_done:
            if not request.headers.get(OWNER_PIN_HEADER):
                return False
        elif not code:
            return False
        try:
            guard(request, code)
        except HTTPException:
            return False
        return True

    @router.get("/api/setup")
    async def get_state(request: Request, x_setup_code: str | None = Header(None)) -> dict[str, Any]:
        """Rig and wrong-sender addresses only for the owner (or the setup code before setup)."""
        return state(authed(request, x_setup_code))

    def state(full: bool) -> dict[str, Any]:
        s = current()
        c = hub.config
        return {
            "product": brand.PRODUCT_NAME,
            "setup_done": bool(s and s.setup_done),
            "has_settings": s is not None,          # earlier settings (and PINs) exist; blank PIN fields keep them
            "has_staff_pin": bool(s and s.staff_pin),   # a staff PIN is required: the form asks for one until set
            "needs_code": not (s and s.setup_done),
            "name": c.cafe.name, "tagline": c.cafe.tagline, "logo": c.cafe.logo,
            "wifi_ssid": c.cafe.wifi_ssid, "wifi_security": c.cafe.wifi_security,   # never the password
            "accent": c.cafe.branding.get("--brand-accent", "#E10600"),
            "open_hour": c.owner.open_hour, "close_hour": c.owner.close_hour,
            "hub_address": hub.hub_address(), "http_port": c.network.http_port, "udp_port": c.network.udp_port,
            "authed": full,                         # rig addresses and editing need the owner PIN
            "rigs": rig_rows(full),
            "warnings": [{"code": w["code"], "message": w["message"]}
                         for w in hub.admin_warnings()] + wrong_senders(full),
        }

    def wrong_senders(full: bool) -> list[dict[str, Any]]:
        warnings = hub.wrong_sender_warnings()
        if full:
            return [{"code": w["code"], "message": w["message"]} for w in warnings]
        return [{"code": "wrong_format_sender",
                 "message": "A PC is sending telemetry in the wrong format: set UDP Format to 2025."}] if warnings else []

    def rig_rows(full: bool = True) -> list[dict[str, Any]]:
        now = time.monotonic()
        rows = []
        for r in hub.registry.all():
            row = {"rig_id": None, "name": r.name, "number": r.auto_name, "colour": rig_colour(r),
                   "state_text": hub.state_text(r.ip, now), "moving": hub.rig_moving(r.ip, now)}
            if full:
                row.update({"rig_id": r.ip, "address": r.ip, "custom_name": r.custom_name,
                            "has_session": hub.drivers.get(r.ip) is not None})
            rows.append(row)
        return rows

    def rig_edit(fn, *args) -> dict[str, Any]:
        try:
            fn(*args)
        except RigError as exc:
            raise HTTPException(400, str(exc)) from None
        return {"authed": True, "rigs": rig_rows()}

    # The rig endpoints are async so they run on the event loop, like the packet receive path that also
    # changes the rig registry: no edit runs while a packet is half-way through.

    @router.get("/api/setup/rigs")
    async def rigs(request: Request, x_setup_code: str | None = Header(None)) -> dict[str, Any]:
        """The rig list with "moving now", polled by the setup page to tell which rig is which."""
        full = authed(request, x_setup_code)
        return {"authed": full, "rigs": rig_rows(full)}

    @router.put("/api/setup/rigs/{rig_id}")
    async def rename_rig(request: Request, rig_id: str, body: dict[str, Any] = Body(...),
                   x_setup_code: str | None = Header(None)) -> dict[str, Any]:
        """{"name": "..."}: up to 16 characters, shown on the TV; empty goes back to the rig's number."""
        guard(request, x_setup_code)
        return rig_edit(hub.rename_rig, rig_id, body.get("name"))

    @router.delete("/api/setup/rigs/{rig_id}")
    async def forget_rig(request: Request, rig_id: str, x_setup_code: str | None = Header(None)) -> dict[str, Any]:
        """Forget a rig that no longer exists (and its check-in code)."""
        guard(request, x_setup_code)
        return rig_edit(hub.forget_rig, rig_id)

    @router.post("/api/setup/rigs/{rig_id}/same-as")
    async def same_rig_as(request: Request, rig_id: str, body: dict[str, Any] = Body(...),
                    x_setup_code: str | None = Header(None)) -> dict[str, Any]:
        """{"old": rig_id}: this rig is the PC that used to be `old` (it got a new address)."""
        guard(request, x_setup_code)
        return rig_edit(hub.merge_rig, str(body.get("old") or ""), rig_id)

    @router.post("/api/setup/address/ok")
    async def address_ok(request: Request, x_setup_code: str | None = Header(None)) -> dict[str, Any]:
        """"OK, done" on the address-change warning."""
        guard(request, x_setup_code)
        hub.address_watch.acknowledge()
        return state(True)

    @router.post("/api/setup")
    def save(request: Request, body: dict[str, Any], x_setup_code: str | None = Header(None)) -> dict[str, Any]:
        guard(request, x_setup_code)
        old = current()
        body = dict(body)
        for key in ("owner_pin", "staff_pin"):
            # Only PINs the hub stored itself may be hashes; one sent in would let a copied hash stand in for a PIN.
            if isinstance(body.get(key), str) and is_hashed(body[key].strip()):
                raise HTTPException(422, "A PIN is 4 to 8 digits.")
        body.pop("remove_staff_pin", None)      # older pages: the staff PIN can't be removed any more
        if old is not None:
            # /api/setup never returns PINs, so the form's PIN fields start empty: blank means "keep the current one".
            # Applies whenever settings exist, also after `setup-code --reset` (setup_done is false again then).
            if not body.get("owner_pin"):
                body["owner_pin"] = old.owner_pin
            if not body.get("staff_pin"):
                body["staff_pin"] = old.staff_pin
        if not body.get("staff_pin"):
            raise HTTPException(400, "Choose a staff PIN (4 to 8 digits). It may be the same as the owner PIN.")
        if not (body.get("wifi_ssid") or "").strip():
            body["wifi_password"] = ""                      # clearing the SSID clears the stored password too
        elif old is not None and not body.get("wifi_password") and body.get("wifi_security", "WPA") == "WPA":
            body["wifi_password"] = old.wifi_password       # blank keeps the Wi-Fi password, like the PINs
        try:
            s = CafeSettings(**{**body, "logo": old.logo if old else hub.config.cafe.logo, "setup_done": True})
        except ValidationError as exc:
            raise HTTPException(400, _plain_errors(exc)) from None
        store.save(s)
        apply_settings(hub.config, s)
        hub.apply_hours()
        hub.startup_warnings = [w for w in hub.startup_warnings if w["code"] != "settings_damaged"]   # dealt with
        setup_code.clear()                     # used up: from now on the owner PIN guards /setup
        return state(True)

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
