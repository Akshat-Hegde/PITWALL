"""Hub-served HTML pages: the product name comes from brand.py, filled in where the page says {{PRODUCT_NAME}}, and
the game's telemetry settings (U1) from rig_setup.py where it says {{RIG_SETUP_...}}."""

from __future__ import annotations

from pathlib import Path

from fastapi.responses import HTMLResponse

from .. import brand, rig_setup


def render_page(path: Path, fill: dict[str, str] | None = None, headers: dict[str, str] | None = None) -> HTMLResponse:
    """`fill` replaces further {{KEY}} placeholders with already-escaped text."""
    html = path.read_text(encoding="utf-8").replace("{{PRODUCT_NAME}}", brand.PRODUCT_NAME)
    for key, value in {**rig_setup.page_fill(), **(fill or {})}.items():
        html = html.replace("{{" + key + "}}", value)
    return HTMLResponse(html, headers=headers)
