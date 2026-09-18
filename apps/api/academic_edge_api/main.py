"""FastAPI application factory for Academic Edge.

``create_app()`` wires CORS, the correlation-id middleware, structured logging,
the RFC-7807-ish error envelope, the ``/v1`` routers and the OpenAPI metadata.
Importing this module has no side effects: nothing connects, migrates or seeds
until the worker CLI or a request touches the session dependency.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from academic_edge_api import __version__
from academic_edge_api.deps import get_engine
from academic_edge_api.observability import configure_logging, log_event, new_correlation_id
from academic_edge_api.routers import catalog, insights, stream
from academic_edge_api.settings import get_settings

API_TITLE = "Academic Edge"
API_DESCRIPTION = (
    "Read-only football market-intelligence API. Ingests permitted sports data, "
    "resolves provider entities into a canonical model, compares equivalent "
    "markets and reports arbitrage / model-vs-market value with full evidence. "
    "It never places bets, signs wallets or holds bookmaker credentials."
)
API_VERSION = __version__


async def correlation_middleware(request: Request, call_next: Any) -> Any:
    """Attach a correlation id, time the request, log it as JSON."""
    correlation_id = request.headers.get("X-Correlation-ID") or new_correlation_id()
    request.state.correlation_id = correlation_id
    started = time.monotonic()
    response = await call_next(request)
    latency_ms = int((time.monotonic() - started) * 1000)
    response.headers["X-Correlation-ID"] = correlation_id
    log_event(
        20,
        "request",
        correlation_id=correlation_id,
        latency_ms=latency_ms,
        extra={
            "method": request.method,
            "path": request.url.path,
            "status": getattr(response, "status_code", None),
        },
    )
    return response


def create_app() -> FastAPI:
    """Build the application (used by uvicorn, the tests and the worker)."""
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title=API_TITLE,
        description=API_DESCRIPTION,
        version=API_VERSION,
        openapi_tags=[
            {"name": "Catalog", "description": "Health, sources, events, markets, quotes."},
            {"name": "Insights", "description": "Opportunities, review, predictions, alerts, ledger."},
            {"name": "Stream", "description": "Server-Sent Events."},
        ],
    )
    app.state.engine = get_engine(settings)
    app.state.settings = settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["X-API-Key", "X-Correlation-ID", "Last-Event-ID", "Content-Type"],
        expose_headers=["X-Correlation-ID", "X-Academic-Edge-Dev-Auth"],
    )
    app.middleware("http")(correlation_middleware)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        log_event(
            40,
            "unhandled error",
            correlation_id=getattr(request.state, "correlation_id", None),
            extra={"error": f"{type(exc).__name__}: {exc}"},
        )
        return JSONResponse(
            status_code=500,
            content={
                "type": "about:blank",
                "title": "Internal Server Error",
                "status": 500,
                "detail": "An unexpected error occurred. The request id is in X-Correlation-ID.",
                "correlation_id": getattr(request.state, "correlation_id", None),
            },
        )

    app.include_router(catalog.router, prefix="/v1", tags=["Catalog"])
    app.include_router(insights.router, prefix="/v1", tags=["Insights"])
    app.include_router(stream.router, prefix="/v1", tags=["Stream"])

    @app.get("/", include_in_schema=False)
    def root() -> dict[str, str]:
        return {"service": "academic-edge", "docs": "/docs", "health": "/v1/health"}

    return app


app = create_app()