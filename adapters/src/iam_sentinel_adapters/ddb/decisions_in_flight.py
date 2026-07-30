"""`SentinelDecisionsInFlight` table client (phase-05 §3) — the simplest
key shape in the inventory: partition-key-only with a 1-hour TTL, used to
track a correlation ID from Prime's dispatch until a `DecisionRecord`
lands.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from iam_sentinel_adapters.ddb.base import DynamoDbHelper
from iam_sentinel_adapters.settings import settings

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

    from iam_sentinel_adapters.circuit_breaker import BreakerAccessor

_TTL_HOURS = 1


class DecisionsInFlightClient:
    def __init__(
        self,
        *,
        table_name: str | None = None,
        table: Table | None = None,
        breaker: BreakerAccessor | None = None,
    ) -> None:
        self._helper = DynamoDbHelper(
            table_name or settings.decisions_in_flight_table, table=table, breaker=breaker
        )

    def start(self, correlation_id: str, payload: dict[str, Any]) -> None:
        expires_at = int((datetime.now(UTC) + timedelta(hours=_TTL_HOURS)).timestamp())
        self._helper.put_item({**payload, "correlation_id": correlation_id, "expires_at": expires_at})

    def get(self, correlation_id: str) -> dict[str, Any] | None:
        return self._helper.get_item({"correlation_id": correlation_id})

    def complete(self, correlation_id: str) -> None:
        self._helper.delete_item({"correlation_id": correlation_id})
