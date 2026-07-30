"""`apigatewaymanagementapi:PostToConnection` adapter (backend phase-02 §4-5)
-- the one boto3 surface `backend/src/iam_sentinel_backend/ws/` is allowed to
reach, per the repo-wide boto3-only-through-adapters rule.

A fresh client per distinct `endpoint_url` is cached for the adapter's
lifetime rather than per-invocation: `endpoint_url` is derived from the
WebSocket connection's own domain/stage (phase-07 §4's `ws_default` stub
already established this), which does not change across frames on the same
connection, so re-building the client on every `PostToConnection` call would
be pure overhead in a Lambda execution environment that gets reused across
invocations.
"""

from __future__ import annotations

from typing import Any

import boto3
from botocore.exceptions import ClientError

from iam_sentinel_adapters.errors import ConnectionGoneError, NetworkError, ThrottlingError
from iam_sentinel_adapters.settings import settings


class ManagementApiClient:
    def __init__(self) -> None:
        self._clients: dict[str, Any] = {}

    def _client_for(self, endpoint_url: str) -> Any:
        client = self._clients.get(endpoint_url)
        if client is None:
            client = boto3.client(
                "apigatewaymanagementapi", region_name=settings.region, endpoint_url=endpoint_url
            )
            self._clients[endpoint_url] = client
        return client

    def post_to_connection(self, *, endpoint_url: str, connection_id: str, data: bytes) -> None:
        client = self._client_for(endpoint_url)
        try:
            client.post_to_connection(ConnectionId=connection_id, Data=data)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code == "GoneException":
                raise ConnectionGoneError(
                    f"connection {connection_id!r} is gone (client disconnected)"
                ) from exc
            if code in {"LimitExceededException", "ThrottlingException"}:
                raise ThrottlingError(str(exc)) from exc
            raise NetworkError(str(exc)) from exc

    def forget(self, endpoint_url: str) -> None:
        """Drop a cached client, e.g. after a `ConnectionGoneError` for the
        last connection on a given stage -- purely a memory-bound cleanup,
        never required for correctness (a stale cached client just means a
        future call rebuilds against the same, still-valid, endpoint).
        """
        self._clients.pop(endpoint_url, None)
