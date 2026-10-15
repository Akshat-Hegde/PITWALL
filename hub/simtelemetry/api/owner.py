"""Owner analytics page (/owner) and its API, behind its own PIN ([owner] pin, header X-Owner-Pin).

The page shows business figures, so it stays locked until a PIN is set in the config.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from ..core.analytics import Analytics
from ..core.backup import last_backup
from .pages import render_page
from .staff import PinGuard

if TYPE_CHECKING:
    from ..hub import Hub

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
        if not config.features.owner:
            raise HTTPException(404, "The owner page is switched off on this hub.")
        if not config.owner.pin:
            raise HTTPException(403, "Finish setup first: open the setup page on the hub PC and choose an owner PIN.")
        guard(request)

    @router.get("/owner", response_class=HTMLResponse, include_in_schema=False)
    def page() -> HTMLResponse:
        return render_page(OWNER_PAGE)

    @router.get("/api/owner/report", dependencies=[Depends(check)])
    def report(days: int = 30) -> dict[str, Any]:
        _sync_hours()
        return {"cafe": config.cafe.name, **analytics.report(days),
                "pin_alerts": [a["text"] for a in hub.pin_attempts.alert_list()]}

    @router.get("/api/owner/export.csv", dependencies=[Depends(check)])
    def export(kind: str = "daily", days: int = 30) -> Response:
        if kind not in CSV_KINDS:
            raise HTTPException(400, f"kind is one of {', '.join(CSV_KINDS)}")
        _sync_hours()
        name = f"{kind}-last-{days}-days.csv"
        return Response(analytics.csv(kind, max(1, min(366, days))), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    def backup_status() -> dict[str, Any]:
        return {"last": last_backup(config.backups_dir), "directory": str(config.backups_dir)}

    @router.get("/api/owner/backup", dependencies=[Depends(check)])
    def backup_get() -> dict[str, Any]:
        return backup_status()

    @router.post("/api/owner/backup", dependencies=[Depends(check)])
    def backup_now() -> dict[str, Any]:
        try:
            hub.run_backup()
        except (OSError, sqlite3.Error) as exc:
            raise HTTPException(500, f"The backup failed: {exc}") from None
        return backup_status()

    return router
