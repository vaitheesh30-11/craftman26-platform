"""Correlation-id + timing middleware (phase-00 §3 Correlation ID).

Extracted from `X-Correlation-Id` if present (and ULID-shaped); else a new
ULID is minted at the boundary. Written into Powertools' logger context
(`append_keys`) and the X-Ray segment annotation, then echoed back on the
response so a caller can always find their own request in logs.
"""

from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING

from aws_lambda_powertools import Logger, Tracer
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from iam_sentinel_backend.ids import new_ulid
from iam_sentinel_backend.settings import settings

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response

_ULID_RE = re.compile(r"^01[0-9A-HJKMNP-TV-Z]{24}$")

logger = Logger(service=settings.service_name)
tracer = Tracer(service=settings.service_name)


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Establishes `request.state.correlation_id` before the route runs, and
    logs one structured line per request with total duration.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        incoming = request.headers.get(settings.correlation_header_name)
        correlation_id = incoming if incoming and _ULID_RE.match(incoming) else new_ulid()
        request.state.correlation_id = correlation_id

        logger.append_keys(correlation_id=correlation_id)
        tracer.put_annotation(key="correlation_id", value=correlation_id)

        start = time.monotonic()
        response = await call_next(request)
        duration_ms = int((time.monotonic() - start) * 1000)

        response.headers[settings.correlation_header_name] = correlation_id
        logger.info(
            "request_completed",
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        return response
