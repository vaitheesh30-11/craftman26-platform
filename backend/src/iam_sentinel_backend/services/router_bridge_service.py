"""Router Bridge (backend phase-01 §5): `POST /analyze/*`, `/enrich/policy`,
`/resolve/*`, `/scan/*`, `/emergency/kill-session`, and `GET /monitor/
shadow-violations` all dispatch here. `functions/router` (agents phase-15
dual-mode) is the callee and does not exist yet -- see
`iam_sentinel_adapters.compute.lambda_client`'s module docstring; this
service is fully testable today against a mocked `LambdaInvokeClient`.
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from fastapi import status
from iam_sentinel_adapters.errors import SentinelAdapterError

from iam_sentinel_backend.errors import SentinelHTTPException
from iam_sentinel_backend.schemas.router_bridge import FastPathResponse, FastPathTarget

if TYPE_CHECKING:
    from iam_sentinel_adapters.compute.lambda_client import LambdaInvokeClient

    from iam_sentinel_backend.auth.principal import Principal


class RouterBridgeService:
    def __init__(self, lambda_client: LambdaInvokeClient, *, function_name: str) -> None:
        self._lambda = lambda_client
        self._function_name = function_name

    def dispatch(
        self,
        *,
        target: FastPathTarget,
        payload: dict[str, object],
        principal: Principal,
        correlation_id: str,
    ) -> FastPathResponse:
        request_payload: dict[str, Any] = {
            "mode": "fast",
            "target": target,
            "payload": payload,
            "principal": principal.arn,
            "correlation_id": correlation_id,
        }
        try:
            raw = self._lambda.invoke(self._function_name, request_payload)
        except SentinelAdapterError as exc:
            raise SentinelHTTPException(
                code="ROUTER_DISPATCH_FAILED",
                message=f"fast-path dispatch to {target} failed: {exc}",
                http_status=status.HTTP_502_BAD_GATEWAY,
            ) from exc
        return FastPathResponse(
            target=target,
            verdict=str(raw.get("verdict", "INCONCLUSIVE")),
            reason=str(raw.get("reason", "")),
            findings=list(raw.get("findings", [])),
            remediation=raw.get("remediation"),
        )

    def dispatch_read(self, *, target: FastPathTarget, query: dict[str, object]) -> dict[str, Any]:
        """The one `GET` fast-path route (`/monitor/shadow-violations`, F6)
        -- no `principal`/`correlation_id` envelope since it's a read, not
        an analysis request.
        """
        try:
            return self._lambda.invoke(
                self._function_name, {"mode": "fast", "target": target, "query": query}
            )
        except SentinelAdapterError as exc:
            raise SentinelHTTPException(
                code="ROUTER_DISPATCH_FAILED",
                message=f"fast-path read dispatch to {target} failed: {exc}",
                http_status=status.HTTP_502_BAD_GATEWAY,
            ) from exc
