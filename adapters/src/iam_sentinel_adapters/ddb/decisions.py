"""`SentinelDecisions` table client (phase-01 §3.2) — Prime's post-turn
Lambda is the one and only writer. Key shape per the spec: PK `principal`,
SK `decided_at`.

Callers pass and receive plain dicts, never an agents `DecisionRecord`
model (module boundary, adapters/README.md §1: adapters does not import
from agents/).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from iam_sentinel_adapters.ddb.base import DynamoDbHelper
from iam_sentinel_adapters.settings import settings

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

    from iam_sentinel_adapters.circuit_breaker import BreakerAccessor

_PK_ATTR = "principal"
_SK_ATTR = "decided_at"


class DecisionsClient:
    def __init__(
        self,
        *,
        table_name: str | None = None,
        table: Table | None = None,
        breaker: BreakerAccessor | None = None,
    ) -> None:
        self._helper = DynamoDbHelper(table_name or settings.decisions_table, table=table, breaker=breaker)

    def put(self, decision: dict[str, Any]) -> None:
        """Idempotent by design: `decision_id` is derived from the turn's
        `correlation_id`, so a retried post-turn write for the same turn
        overwrites itself rather than creating a duplicate row -- the real
        duplicate-suppression guard is `IdempotencyClient`, called before
        this ever runs.
        """
        item = {**decision, _PK_ATTR: decision["principal"], _SK_ATTR: decision["decided_at"]}
        self._helper.put_item(item)

    def latest_for_principal(self, principal: str, limit: int = 1) -> list[dict[str, Any]]:
        return self._helper.query(
            key_condition_expression="#pk = :pk",
            expression_attribute_names={"#pk": _PK_ATTR},
            expression_attribute_values={":pk": principal},
            limit=limit,
            scan_index_forward=False,
        )

    def query_since(self, principal: str, since_iso: str, limit: int = 100) -> list[dict[str, Any]]:
        return self._helper.query(
            key_condition_expression="#pk = :pk AND #sk >= :since",
            expression_attribute_names={"#pk": _PK_ATTR, "#sk": _SK_ATTR},
            expression_attribute_values={":pk": principal, ":since": since_iso},
            limit=limit,
        )
