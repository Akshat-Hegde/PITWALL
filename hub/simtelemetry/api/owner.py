"""Owner analytics page (/owner) and its API, behind its own PIN ([owner] pin, header X-Owner-Pin).

The page shows business figures, so it stays locked until a PIN is set in the config.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import ValidationError

from ..core.analytics import Analytics
from ..core.backup import TOO_LONG, BackupFailed, check_folder, last_backup
from ..core.settings import CafeSettings, SettingsDamaged, SettingsStore
from ..licence import INVALID, LicenceError
from .pages import render_page
from .staff import PinGuard

if TYPE_CHECKING:
    from ..hub import Hub

log = logging.getLogger(__name__)

OWNER_PIN_HEADER = "X-Owner-Pin"
OWNER_PAGE = Path(__file__).with_name("owner.html")
CSV_KINDS = ("daily", "sessions", "laps")


def owner_router(hub: Hub) -> APIRouter:
    router = APIRouter()
    config = hub.config
    guard = PinGuard(lambda: config.owner.pin, header=OWNER_PIN_HEADER, attempts=hub.pin_attempts)
    analytics = Analytics(hub.drivers.store, config.day_start_hour, config.owner.open_hour,
                          config.owner.close_hour, rig_label=hub.rig_label)

    def _sync_hours() -> None:
        """Opening hours can change from /setup while the hub runs; use the live values."""
        analytics.open_hour, analytics.close_hour = config.owner.open_hour, config.owner.close_hour
        analytics.day_start_hour = config.day_start_hour

    def check(request: Request) -> None:
        # hub.toml's own switch: the licence never closes the page, so a new code can always be entered here.
        if not config.features.owner:
            raise HTTPException(404, "The owner page is switched off on this hub.")
        if not config.owner.pin:
            raise HTTPException(403, "Finish setup first: open the setup page on the hub PC and choose an owner PIN.")
        guard(request)

    def check_figures(request: Request) -> None:
        """The business figures are the licensed `owner` feature; backups and the Licence card are not."""
        check(request)
        if not hub.features.owner:
            raise HTTPException(403, figures_note())

    def figures_note() -> str:
        return f"Business figures aren't included in this licence. Contact {hub.entitlements.supplier} to add them."

    @router.get("/owner", response_class=HTMLResponse, include_in_schema=False)
    def page() -> HTMLResponse:
        return render_page(OWNER_PAGE)

    @router.get("/api/owner/report", dependencies=[Depends(check_figures)])
    def report(days: int = 30) -> dict[str, Any]:
        _sync_hours()
        return {"cafe": config.cafe.name, **analytics.report(days),
                "pin_alerts": [a["text"] for a in hub.pin_attempts.alert_list()]}

    @router.get("/api/owner/export.csv", dependencies=[Depends(check_figures)])
    def export(kind: str = "daily", days: int = 30) -> Response:
        if kind not in CSV_KINDS:
            raise HTTPException(400, f"kind is one of {', '.join(CSV_KINDS)}")
        _sync_hours()
        name = f"{kind}-last-{days}-days.csv"
        return Response(analytics.csv(kind, max(1, min(366, days))), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    settings_store = SettingsStore(config.data_dir)

    def backup_status() -> dict[str, Any]:
        folder = config.backups_dir
        try:
            last = last_backup(folder)
        except OSError:                       # a USB stick that went away while looking
            last = None
        chosen = config.owner_backup_dir
        return {"last": last, "directory": str(folder), "chosen": str(chosen) if chosen else "",
                "default_directory": str(config.default_backups_dir), **hub.backup_status.to_json(),
                "warning": hub.backup_warning()}

    @router.get("/api/owner/backup", dependencies=[Depends(check)])
    def backup_get() -> dict[str, Any]:
        return backup_status()

    @router.post("/api/owner/backup", dependencies=[Depends(check)])
    def backup_now() -> dict[str, Any]:
        try:
            hub.run_backup()
        except BackupFailed as exc:          # plain English; the raw error is in the log
            raise HTTPException(503, exc.text) from None
        return backup_status()

    @router.post("/api/owner/backup/folder", dependencies=[Depends(check)])
    def backup_folder(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        r"""{"folder": "E:\Backups"}: where backups go from now on (checked by writing a small file there);
        empty goes back to the default folder. Kept in settings.json."""
        try:
            folder = check_folder(body.get("folder"), data_dir=config.data_dir)
        except BackupFailed as exc:
            raise HTTPException(400, exc.text) from None
        try:
            current = settings_store.read()
        except SettingsDamaged:
            current = None
        if current is None:
            raise HTTPException(409, "Finish setup first: open the setup page on the hub PC.")
        try:                                 # checked as a whole, so settings.json can never be saved unreadable
            updated = CafeSettings.model_validate({**current.model_dump(), "backup_dir": str(folder) if folder else ""})
        except ValidationError:
            raise HTTPException(400, TOO_LONG) from None
        settings_store.save(updated)
        config.set_owner_backup_dir(folder)
        log.info("Backup folder is now %s", config.backups_dir)
        return backup_status()

    def licence_body() -> dict[str, Any]:
        figures = hub.features.owner
        return {**hub.licence_info(), "figures": figures, "figures_note": None if figures else figures_note(),
                # Shown with the report too; here for when the figures aren't licensed.
                "pin_alerts": [a["text"] for a in hub.pin_attempts.alert_list()]}

    @router.get("/api/owner/licence", dependencies=[Depends(check)])
    def licence_get() -> dict[str, Any]:
        return licence_body()

    @router.post("/api/owner/licence", dependencies=[Depends(check)])
    async def licence_post(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        """{"code": "PW1-..."}: a new licence code (add-ons). Applies at once; errors are plain sentences.
        async on purpose: the entitlement hooks change state the feed and the UDP path read, so they run on the
        event loop like those, never in a worker thread (a check and one small file write: quick)."""
        code = body.get("code")
        if not isinstance(code, str) or not code.strip():
            raise HTTPException(400, INVALID)
        try:
            hub.apply_licence(code)
        except LicenceError as exc:
            raise HTTPException(400, str(exc)) from None
        return licence_body()

    return router
