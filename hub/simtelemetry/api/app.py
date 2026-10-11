"""HTTP API, dashboard WebSocket feed (/ws) and the built dashboard files (/)."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from ..core.feed import FeedBuilder, FeedConnection
from ..hub import Hub
from .staff import staff_router

log = logging.getLogger(__name__)

DEFAULT_DASHBOARD_DIR = Path(__file__).resolve().parents[3] / "dashboard" / "dist"

NOT_BUILT_PAGE = """<!doctype html><meta charset="utf-8"><title>Dashboard not built</title>
<body style="font-family:sans-serif;background:#18232d;color:#eef3f6;padding:2rem;max-width:40em">
<h1>The dashboard hasn't been built yet</h1>
<p>The hub is running and receiving telemetry, but there are no dashboard files in
<code>{directory}</code>.</p>
<p>Build them once (needs Node.js 20+), then reload this page:</p>
<pre>cd dashboard
npm install
npm run build</pre>
<p>Hub status: <a href="/api/health" style="color:#36c5f0">/api/health</a></p>
</body>"""


def _dumps(msg: dict[str, Any]) -> str:
    return json.dumps(msg, separators=(",", ":"), allow_nan=False)


def create_app(hub: Hub, dashboard_dir: Path | None = None) -> FastAPI:
    app = FastAPI(title="Sim Telemetry Hub", docs_url="/api/docs", openapi_url="/api/openapi.json")
    builder = FeedBuilder(hub)

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return hub.health_snapshot()

    app.include_router(staff_router(hub))

    @app.websocket("/ws")
    async def feed(websocket: WebSocket) -> None:
        await websocket.accept()
        conn = FeedConnection(builder)
        client = f"{websocket.client.host}:{websocket.client.port}" if websocket.client else "?"
        log.info("Dashboard connected from %s", client)
        loop = asyncio.get_running_loop()
        interval = 1.0 / builder.frame_hz
        try:
            await websocket.send_text(_dumps(conn.start(time.monotonic())))
            due = loop.time()
            while True:
                due += interval
                delay = due - loop.time()
                if delay > 0:
                    await asyncio.sleep(delay)
                else:
                    due = loop.time()  # fell behind (slow client): skip ahead instead of bursting
                for msg in conn.tick(time.monotonic()):
                    await websocket.send_text(_dumps(msg))
        except (WebSocketDisconnect, RuntimeError, OSError):
            pass  # client went away; it reconnects and gets a fresh snapshot
        finally:
            log.info("Dashboard disconnected from %s", client)

    directory = dashboard_dir or hub.config.dashboard.directory or DEFAULT_DASHBOARD_DIR
    if (directory / "index.html").is_file():
        @app.get("/portrait", include_in_schema=False)
        def portrait() -> FileResponse:
            """Portrait layout for vertical screens: the same dashboard, which reads the path."""
            return FileResponse(directory / "index.html")

        app.mount("/", StaticFiles(directory=directory, html=True), name="dashboard")
    else:
        log.warning("Dashboard not built: no index.html in %s (run `npm run build` in dashboard/)", directory)

        @app.get("/", response_class=HTMLResponse)
        def not_built() -> str:
            return NOT_BUILT_PAGE.format(directory=directory)

    return app
