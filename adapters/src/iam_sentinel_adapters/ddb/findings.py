"""`SentinelFindings` table client (phase-05 §3-4).

Key attributes use the `#`-joined composite convention established in
aws-infra ADR 0005: `account_id#feature_id` (PK), `finding_id#detected_at`
(SK). Every expression below must alias them via `ExpressionAttributeNames`
-- DynamoDB's expression grammar treats a bare `#` as a name-placeholder
marker, so a literal `#` inside an unaliased attribute name breaks parsing.

Callers pass and receive plain dicts, never an agents `Finding` model —
adapters does not import from `agents/` (module boundary, README §1).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from iam_sentinel_adapters.ddb.base import DynamoDbHelper
from iam_sentinel_adapters.settings import settings

if TYPE_CHECKING:
    from datetime import datetime

    from mypy_boto3_dynamodb.service_resource import Table

    from iam_sentinel_adapters.circuit_breaker import BreakerAccessor

_PK_ATTR = "account_id#feature_id"
_SK_ATTR = "finding_id#detected_at"


class FindingsClient:
    def __init__(
        self,
        *,
        table_name: str | None = None,
        table: Table | None = None,
        breaker: BreakerAccessor | None = None,
    ) -> None:
        self._helper = DynamoDbHelper(table_name or settings.findings_table, table=table, breaker=breaker)

    def put(self, finding: dict[str, Any]) -> None:
        item = {
            **finding,
            _PK_ATTR: f"{finding['account_id']}#{finding['feature_id']}",
            _SK_ATTR: f"{finding['finding_id']}#{finding['detected_at']}",
        }
        self._helper.put_item(item)

    def get(self, account_id: str, feature_id: str, finding_id: str) -> dict[str, Any] | None:
        matches = self._helper.query(
            key_condition_expression="#pk = :pk AND begins_with(#sk, :prefix)",
            expression_attribute_names={"#pk": _PK_ATTR, "#sk": _SK_ATTR},
            expression_attribute_values={
                ":pk": f"{account_id}#{feature_id}",
                ":prefix": f"{finding_id}#",
            },
            limit=1,
        )
        return matches[0] if matches else None

    def query_by_severity(self, severity: str, since: datetime, limit: int = 100) -> list[dict[str, Any]]:
        return self._helper.query(
            key_condition_expression="severity = :sev AND detected_at >= :since",
            expression_attribute_values={":sev": severity, ":since": since.isoformat()},
            index_name="severity-index",
            limit=limit,
        )

    def update_status(self, account_id: str, feature_id: str, finding_id: str, status: str) -> None:
        existing = self.get(account_id, feature_id, finding_id)
        if existing is None:
            raise KeyError(f"no finding {finding_id!r} for {account_id}/{feature_id}")

        self._helper.update_item(
            {_PK_ATTR: existing[_PK_ATTR], _SK_ATTR: existing[_SK_ATTR]},
            update_expression="SET #status = :status",
            expression_attribute_names={"#status": "status"},
            expression_attribute_values={":status": status},
        )
