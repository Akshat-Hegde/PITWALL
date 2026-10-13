"""Hub-served HTML pages: the product name comes from brand.py, filled in where the page says {{PRODUCT_NAME}}."""

from __future__ import annotations

from pathlib import Path

from fastapi.responses import HTMLResponse

from .. import brand


def render_page(path: Path) -> HTMLResponse:
    html = path.read_text(encoding="utf-8").replace("{{PRODUCT_NAME}}", brand.PRODUCT_NAME)
    return HTMLResponse(html)
