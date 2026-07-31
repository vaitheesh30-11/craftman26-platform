"""Standard exception hierarchy + FastAPI exception handlers (phase-00 §3-4).

Every response -- success or failure -- uses the envelope:

    { "ok": true,  "data": { ... } }
    { "ok": false, "error": { "code": "...", "message": "...", "correlation_id": "..." } }

`register_exception_handlers` wires both `SentinelHTTPException` and the
domain exceptions raised by `iam_sentinel_adapters.errors` to the correct
HTTP status per phase-00 §4's mapping table. Unhandled exceptions become a
500 with no stack trace ever leaked to the caller.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aws_lambda_powertools import Logger
from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse
from iam_sentinel_adapters.errors import (
    AccessDeniedError,
    BudgetExceededError,
    CircuitOpenError,
    EvidenceVerificationError,
    GuardrailInterventionError,
    SanitizerRejection,
    ValidationError,
    ZelkovaError,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from fastapi import FastAPI

logger = Logger(child=True)


class SentinelHTTPException(HTTPException):
    """Domain HTTP error every router should raise instead of a bare
    `HTTPException` -- carries a stable machine-readable `code` alongside
    the human `message`, per the response envelope's `error.code` field.
    """

    def __init__(self, *, code: str, message: str, http_status: int) -> None:
        super().__init__(status_code=http_status, detail=message)
        self.code = code
        self.message = message


# Domain exception -> (code, http status), phase-00 §4's mapping table.
_DOMAIN_EXCEPTION_STATUS: dict[type[Exception], tuple[str, int]] = {
    SanitizerRejection: ("SANITIZER_REJECTION", status.HTTP_400_BAD_REQUEST),
    GuardrailInterventionError: ("GUARDRAIL_INTERVENTION", status.HTTP_400_BAD_REQUEST),
    ValidationError: ("VALIDATION_ERROR", status.HTTP_400_BAD_REQUEST),
    AccessDeniedError: ("ACCESS_DENIED", status.HTTP_403_FORBIDDEN),
    BudgetExceededError: ("BUDGET_EXCEEDED", status.HTTP_429_TOO_MANY_REQUESTS),
    CircuitOpenError: ("CIRCUIT_OPEN", status.HTTP_503_SERVICE_UNAVAILABLE),
    ZelkovaError: ("ZELKOVA_ERROR", status.HTTP_500_INTERNAL_SERVER_ERROR),
    # backend phase-04 §4 step 3: tampered/corrupt evidence returns 502, not
    # 500 -- the failure is in the stored artifact/signature, not this
    # service's own logic.
    EvidenceVerificationError: ("EVIDENCE_VERIFICATION_FAILED", status.HTTP_502_BAD_GATEWAY),
}


def _error_envelope(*, code: str, message: str, correlation_id: str) -> dict[str, object]:
    return {
        "ok": False,
        "error": {"code": code, "message": message, "correlation_id": correlation_id},
    }


def _correlation_id(request: Request) -> str:
    return str(getattr(request.state, "correlation_id", "unknown"))


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(SentinelHTTPException)
    async def _handle_sentinel_http(request: Request, exc: SentinelHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_envelope(
                code=exc.code, message=exc.message, correlation_id=_correlation_id(request)
            ),
        )

    @app.exception_handler(HTTPException)
    async def _handle_http(request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_envelope(
                code="HTTP_ERROR", message=str(exc.detail), correlation_id=_correlation_id(request)
            ),
        )

    for exc_type, (code, http_status) in _DOMAIN_EXCEPTION_STATUS.items():

        def _make_handler(
            bound_code: str, bound_status: int
        ) -> Callable[[Request, Exception], Awaitable[JSONResponse]]:
            async def _handler(request: Request, exc: Exception) -> JSONResponse:
                logger.warning("domain_exception", code=bound_code, error=str(exc))
                return JSONResponse(
                    status_code=bound_status,
                    content=_error_envelope(
                        code=bound_code, message=str(exc), correlation_id=_correlation_id(request)
                    ),
                )

            return _handler

        app.add_exception_handler(exc_type, _make_handler(code, http_status))

    @app.exception_handler(Exception)
    async def _handle_unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_exception", error=str(exc))
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_error_envelope(
                code="INTERNAL_ERROR",
                message="An internal error occurred.",
                correlation_id=_correlation_id(request),
            ),
        )
