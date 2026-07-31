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
_MAX_SCAN_PAGES = 10


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
        self._helper.put_item(
            {**payload, "correlation_id": correlation_id, "expires_at": expires_at}
        )

    def get(self, correlation_id: str) -> dict[str, Any] | None:
        return self._helper.get_item({"correlation_id": correlation_id})

    def complete(self, correlation_id: str) -> None:
        self._helper.delete_item({"correlation_id": correlation_id})

    def cancel(self, correlation_id: str) -> None:
        """Mark a turn canceled (backend phase-02 §4 step 2 `action=="cancel"`).

        `update_item` rather than `put_item`: the row already carries the
        original dispatch payload written by `start()`, and this must not
        clobber it -- the streaming fan-out reads `canceled` on its next
        poll without losing the rest of the record.
        """
        self._helper.update_item(
            {"correlation_id": correlation_id},
            update_expression="SET canceled = :canceled",
            expression_attribute_values={":canceled": True},
        )

    def is_canceled(self, correlation_id: str) -> bool:
        item = self.get(correlation_id)
        return bool(item and item.get("canceled"))

    def list_all(self, *, max_pages: int = _MAX_SCAN_PAGES) -> list[dict[str, Any]]:
        """Full-table scan, bounded by `max_pages` (agents phase-17 §6 Step
        1: the watchdog scanner needs every in-flight row to find stuck
        ones -- no GSI exists for "every row regardless of correlation_id",
        same bounded-scan-fallback precedent as `FaultsClient.list_recent`
        and `DecisionsClient.get_by_id` use for the same reason: this table
        has no secondary index and none is warranted for a table whose rows
        are always short-lived (1-hour TTL).
        """
        items: list[dict[str, Any]] = []
        exclusive_start_key: dict[str, Any] | None = None
        for _ in range(max_pages):
            page, exclusive_start_key = self._helper.scan_page(
                limit=100, exclusive_start_key=exclusive_start_key
            )
            items.extend(page)
            if exclusive_start_key is None:
                break
        return items
