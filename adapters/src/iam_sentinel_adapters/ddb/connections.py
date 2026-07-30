"""`SentinelConnections` table client (backend phase-02 §2). Tracks the
WebSocket `connectionId -> principal/session_id` binding `$default` needs to
reject cross-connection principal leakage (phase-02 §8 risk) and to resume a
session's identity across frames without re-authenticating every message.

Key shape: `aws-infra`'s `api_stack.py::_build_connections_table` already
provisions this table with `connection_id` as the sole partition key and
`expires_at` as the TTL attribute (phase-07 §4) -- this client writes exactly
that shape plus the `principal`/`session_id`/`connected_at` attributes
phase-02 §2's deliverable list calls for. `auth_kind` is optional context
carried over from the WebSocket authorizer, not a phase-02 contract field.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from iam_sentinel_adapters.ddb.base import DynamoDbHelper
from iam_sentinel_adapters.settings import settings

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

    from iam_sentinel_adapters.circuit_breaker import BreakerAccessor

_CONNECTION_TTL_HOURS = 1


class ConnectionsClient:
    def __init__(
        self,
        *,
        table_name: str | None = None,
        table: Table | None = None,
        breaker: BreakerAccessor | None = None,
    ) -> None:
        self._helper = DynamoDbHelper(
            table_name or settings.connections_table, table=table, breaker=breaker
        )

    def connect(
        self,
        *,
        connection_id: str,
        principal: str,
        session_id: str,
        auth_kind: str = "unknown",
    ) -> None:
        expires_at = int((datetime.now(UTC) + timedelta(hours=_CONNECTION_TTL_HOURS)).timestamp())
        self._helper.put_item(
            {
                "connection_id": connection_id,
                "principal": principal,
                "session_id": session_id,
                "auth_kind": auth_kind,
                "connected_at": datetime.now(UTC).isoformat(),
                "expires_at": expires_at,
            }
        )

    def get(self, connection_id: str) -> dict[str, Any] | None:
        return self._helper.get_item({"connection_id": connection_id})

    def disconnect(self, connection_id: str) -> None:
        self._helper.delete_item({"connection_id": connection_id})
