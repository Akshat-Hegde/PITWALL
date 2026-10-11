"""Story card API (no PIN: customers open these on their phones). Each card is behind a random token."""

from __future__ import annotations

import io
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

if TYPE_CHECKING:
    from ..hub import Hub


def card_router(hub: Hub) -> APIRouter:
    router = APIRouter()

    def find(token: str) -> dict[str, Any]:
        card = hub.drivers.card(token) if hub.config.features.sharing else None
        if card is None:
            raise HTTPException(404, "This card doesn't exist (any more).")
        return card

    @router.get("/api/cards/{token}")
    def card(token: str) -> dict[str, Any]:
        return find(token)

    @router.get("/api/cards/{token}/qr.svg", include_in_schema=False)
    def qr(token: str, request: Request) -> Response:
        """QR code of the card page, as seen from the device asking (the staff page uses this)."""
        import segno
        find(token)
        url = str(request.base_url).rstrip("/") + f"/card/{token}"
        out = io.BytesIO()
        segno.make(url, error="m").save(out, kind="svg", scale=8, border=2, dark="#000", light="#fff")
        return Response(out.getvalue(), media_type="image/svg+xml")

    return router
