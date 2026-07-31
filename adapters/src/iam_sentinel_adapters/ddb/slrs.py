"""`SentinelSLRs` table client (agents phase-09 §3 Step 1).

Key shape: PK `service_principal` only, no sort key -- the table is small
(dozens of rows, one per AWS service that ships a Service-Linked Role), so
`list_all` is a bounded, unindexed scan rather than a query. Callers pass
and receive plain dicts, never an agents-module contract -- adapters does
not import from `agents/` (module boundary, README §1), matching
`findings.py`'s own precedent.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from iam_sentinel_adapters.ddb.base import DynamoDbHelper
from iam_sentinel_adapters.settings import settings

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

    from iam_sentinel_adapters.circuit_breaker import BreakerAccessor

_PK_ATTR = "service_principal"
_MAX_SCAN_PAGES = 20  # bounded: dozens of SLR rows, never an unbounded table


class SlrsClient:
    def __init__(
        self,
        *,
        table_name: str | None = None,
        table: Table | None = None,
        breaker: BreakerAccessor | None = None,
    ) -> None:
        self._helper = DynamoDbHelper(
            table_name or settings.slrs_table, table=table, breaker=breaker
        )

    def put(self, row: dict[str, Any]) -> None:
        self._helper.put_item(row)

    def get(self, service_principal: str) -> dict[str, Any] | None:
        return self._helper.get_item({_PK_ATTR: service_principal})

    def list_all(self) -> list[dict[str, Any]]:
        """Every curated SLR row -- `slr_scan` needs the full DB to check a
        proposed SCP against every known Service-Linked Role, not a subset.
        """
        rows: list[dict[str, Any]] = []
        exclusive_start_key: dict[str, Any] | None = None
        for _ in range(_MAX_SCAN_PAGES):
            page, exclusive_start_key = self._helper.scan_page(
                limit=100, exclusive_start_key=exclusive_start_key
            )
            rows.extend(page)
            if exclusive_start_key is None:
                break
        return rows
