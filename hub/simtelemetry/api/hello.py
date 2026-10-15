"""/hello: the phone test page. Open (no PIN), tiny, offline; never shows an address."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .. import brand
from .pages import render_page

if TYPE_CHECKING:
    from ..hub import Hub

HELLO_PAGE = Path(__file__).with_name("hello.html")


def hello_router(hub: Hub) -> APIRouter:
    router = APIRouter()

    @router.get("/hello", response_class=HTMLResponse, include_in_schema=False)
    def hello(request: Request) -> HTMLResponse:
        client = request.client.host if request.client else None
        if hub.phone_test.record(client, hub.own_addresses()):
            fill = {"HELLO_KIND": "ok", "HELLO_MARK": "✓", "HELLO_TITLE": "It works",
                    "HELLO_TEXT": f"Your phone can reach {brand.PRODUCT_NAME}. Check-in and cards will work."}
        else:
            fill = {"HELLO_KIND": "self", "HELLO_MARK": "i", "HELLO_TITLE": "This is the hub PC",
                    "HELLO_TEXT": "This page is for testing from a phone: scan the \"Test from your phone\" "
                                  "code with a phone on the guest Wi-Fi."}
        return render_page(HELLO_PAGE, fill, headers={"Cache-Control": "no-store"})

    @router.get("/api/phone-test")
    def phone_test() -> dict[str, Any]:
        """Whether a phone has reached /hello (setup polls this while the owner tests). No addresses."""
        t = hub.phone_test
        return {"reached": t.reached_at is not None,
                "reached_at": round(t.reached_at * 1000) if t.reached_at is not None else None,
                "text": t.status_text()}

    return router
