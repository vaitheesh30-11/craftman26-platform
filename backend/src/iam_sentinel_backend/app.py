"""App factory + Lambda handler (phase-00 §4 Step 1, §5 Step 5).

`create_app()` composes the FastAPI app used both by the Lambda handler
(via `Mangum`) and by tests (via `TestClient`) -- routers land in later
backend phases (phase-01 onward); phase-00 only wires the substrate
(middleware, error handlers, health) every one of them depends on.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from mangum import Mangum

from iam_sentinel_backend.errors import register_exception_handlers
from iam_sentinel_backend.middleware import CorrelationIdMiddleware
from iam_sentinel_backend.settings import settings

_SERVICE_TITLE = "IAM Sentinel Management API"


def create_app() -> FastAPI:
    app = FastAPI(
        title=_SERVICE_TITLE,
        version="0.1.0",
        # Disable Uvicorn/FastAPI's own request logging (phase-00 §7 risk):
        # Powertools' Logger in CorrelationIdMiddleware is the single
        # authoritative request-line log.
        docs_url="/docs" if settings.stage != "prod" else None,
        redoc_url=None,
    )

    app.add_middleware(CorrelationIdMiddleware)
    register_exception_handlers(app)

    @app.get("/health", tags=["operations"])
    def health() -> dict[str, Any]:
        return {"ok": True, "data": {"stage": settings.stage, "commit": settings.commit_sha}}

    return app


app = create_app()

# `lifespan="off"`: API Gateway's Lambda proxy integration is per-invocation
# request/response -- there is no persistent ASGI lifespan to manage across
# invocations, and Mangum's own lifespan probing adds cold-start latency
# phase-00 §6 acceptance criterion (<800ms) can't afford.
handler = Mangum(app, lifespan="off")
