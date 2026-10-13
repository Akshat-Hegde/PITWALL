"""Owner analytics page (/owner) and its API, behind its own PIN ([owner] pin, header X-Owner-Pin).

The page shows business figures, so it stays locked until a PIN is set in the config.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from ..core.analytics import Analytics
from .staff import PinGuard

if TYPE_CHECKING:
    from ..hub import Hub

OWNER_PIN_HEADER = "X-Owner-Pin"
OWNER_PAGE = Path(__file__).with_name("owner.html")
CSV_KINDS = ("daily", "sessions", "laps")


def owner_router(hub: Hub) -> APIRouter:
    router = APIRouter()
    config = hub.config
    guard = PinGuard(lambda: config.owner.pin, header=OWNER_PIN_HEADER)
    analytics = Analytics(hub.drivers.store, config.leaderboard.day_start_hour, config.owner.open_hour,
                          config.owner.close_hour, rig_label=hub.rig_label)

    def _sync_hours() -> None:
        """Opening hours can change from /setup while the hub runs; use the live values."""
        analytics.open_hour, analytics.close_hour = config.owner.open_hour, config.owner.close_hour

    def check(request: Request) -> None:
        if not config.features.owner:
            raise HTTPException(404, "The owner page is switched off ([features] owner).")
        if not config.owner.pin:
            raise HTTPException(403, "Set [owner] pin in config\\hub.toml to use the owner page, then restart the hub.")
        guard(request)

    @router.get("/owner", response_class=HTMLResponse, include_in_schema=False)
    def page() -> str:
        return OWNER_PAGE.read_text(encoding="utf-8")

    @router.get("/api/owner/report", dependencies=[Depends(check)])
    def report(days: int = 30) -> dict[str, Any]:
        _sync_hours()
        return {"cafe": config.cafe.name, **analytics.report(days)}

    @router.get("/api/owner/export.csv", dependencies=[Depends(check)])
    def export(kind: str = "daily", days: int = 30) -> Response:
        if kind not in CSV_KINDS:
            raise HTTPException(400, f"kind is one of {', '.join(CSV_KINDS)}")
        _sync_hours()
        name = f"{kind}-last-{days}-days.csv"
        return Response(analytics.csv(kind, max(1, min(366, days))), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    return router
