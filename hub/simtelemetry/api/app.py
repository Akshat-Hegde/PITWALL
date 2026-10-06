"""HTTP API. The WebSocket feed and dashboard static files are added in later steps."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from ..hub import Hub


def create_app(hub: Hub) -> FastAPI:
    app = FastAPI(title="Sim Telemetry Hub", docs_url="/api/docs", openapi_url="/api/openapi.json")

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return hub.health_snapshot()

    return app
