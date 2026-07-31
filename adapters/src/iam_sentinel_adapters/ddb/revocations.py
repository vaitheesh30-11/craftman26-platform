"""`SentinelRevocations` table client (agents phase-06 §3-4,
docs/DATA_CONTRACTS.md §9). PK `account_id`, SK `role_arn` -- one live item
per role, which is deliberate: a new dispatch on a role already mid-
revocation overwrites the item forward (later `ttl_expires_at`), and that
overwrite IS how phase-06 §4 Step 4's "extend TTL instead of cleaning" is
implemented (`session_kill_cleanup` re-reads the item immediately before
deleting; if it no longer matches the expired snapshot it queried, a newer
dispatch already superseded it, so cleanup skips it -- see
docs/decisions/0023).

`correlation-index` GSI (pk `correlation_id`, sk `attached_at`) is already
provisioned by aws-infra's `foundation_stack.py` (`_TABLES` spec) though
docs/DATA_CONTRACTS.md §9 doesn't enumerate it -- used here rather than a
bounded scan since it already exists.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from iam_sentinel_adapters.ddb.base import DynamoDbHelper
from iam_sentinel_adapters.settings import settings

if TYPE_CHECKING:
    from datetime import datetime

    from mypy_boto3_dynamodb.service_resource import Table

    from iam_sentinel_adapters.circuit_breaker import BreakerAccessor

_GSI_CORRELATION = "correlation-index"
_MAX_SCAN_PAGES = 20


class RevocationsClient:
    def __init__(
        self,
        *,
        table_name: str | None = None,
        table: Table | None = None,
        breaker: BreakerAccessor | None = None,
    ) -> None:
        self._helper = DynamoDbHelper(
            table_name or settings.revocations_table, table=table, breaker=breaker
        )

    def put(self, record: dict[str, Any]) -> None:
        self._helper.put_item(record)

    def get(self, account_id: str, role_arn: str) -> dict[str, Any] | None:
        return self._helper.get_item({"account_id": account_id, "role_arn": role_arn})

    def query_by_correlation_id(
        self, correlation_id: str, *, limit: int = 100
    ) -> list[dict[str, Any]]:
        return self._helper.query(
            key_condition_expression="correlation_id = :cid",
            expression_attribute_values={":cid": correlation_id},
            index_name=_GSI_CORRELATION,
            limit=limit,
        )

    def query_expired(self, now: datetime, *, limit: int = 100) -> list[dict[str, Any]]:
        """Bounded scan: no GSI is keyed on `cleaned`/`ttl_expires_at` alone
        (only `correlation-index` exists), and TTL-cleanup candidates are
        expected to be a small fraction of the table at any given minute.
        """
        collected: list[dict[str, Any]] = []
        exclusive_start_key: dict[str, Any] | None = None
        for _ in range(_MAX_SCAN_PAGES):
            items, exclusive_start_key = self._helper.scan_page(
                filter_expression="ttl_expires_at <= :now AND cleaned = :false",
                expression_attribute_values={":now": now.isoformat(), ":false": False},
                limit=limit,
                exclusive_start_key=exclusive_start_key,
            )
            collected.extend(items)
            if exclusive_start_key is None or len(collected) >= limit:
                break
        return collected[:limit]

    def mark_cleaned(self, account_id: str, role_arn: str, *, cleaned_at: datetime) -> None:
        self._helper.update_item(
            {"account_id": account_id, "role_arn": role_arn},
            update_expression="SET cleaned = :true, cleaned_at = :cleaned_at",
            expression_attribute_values={":true": True, ":cleaned_at": cleaned_at.isoformat()},
        )
