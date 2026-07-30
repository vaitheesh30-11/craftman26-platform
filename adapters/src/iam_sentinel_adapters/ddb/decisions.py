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
_GSI_CORRELATION = "correlation-index"
_MAX_SCAN_PAGES = 10  # bounded fallback for cross-principal `decision_id` lookup


class DecisionsClient:
    def __init__(
        self,
        *,
        table_name: str | None = None,
        table: Table | None = None,
        breaker: BreakerAccessor | None = None,
    ) -> None:
        self._helper = DynamoDbHelper(
            table_name or settings.decisions_table, table=table, breaker=breaker
        )

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

    def list_page(
        self,
        principal: str,
        *,
        since_iso: str | None = None,
        limit: int = 100,
        exclusive_start_key: dict[str, Any] | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        """`GET /decisions` (backend phase-01 §6): paginated, most-recent
        first, scoped to one principal's partition.
        """
        condition = "#pk = :pk"
        values: dict[str, Any] = {":pk": principal}
        if since_iso is not None:
            condition += " AND #sk >= :since"
            values[":since"] = since_iso
        return self._helper.query_page(
            key_condition_expression=condition,
            expression_attribute_values=values,
            expression_attribute_names={"#pk": _PK_ATTR, "#sk": _SK_ATTR},
            limit=limit,
            scan_index_forward=False,
            exclusive_start_key=exclusive_start_key,
        )

    def get_by_correlation_id(self, correlation_id: str) -> dict[str, Any] | None:
        """`chat_service.ask_prime`'s post-turn poll (backend phase-01 §4
        step 5): O(1) via `correlation-index` (`aws-infra`'s
        `foundation_stack.py`), unlike `get_by_id` below -- `correlation_id`
        genuinely is a GSI partition key, `decision_id` is not.
        """
        items, _ = self._helper.query_page(
            key_condition_expression="#cid = :cid",
            expression_attribute_values={":cid": correlation_id},
            expression_attribute_names={"#cid": "correlation_id"},
            index_name=_GSI_CORRELATION,
            limit=1,
            scan_index_forward=False,
        )
        return items[0] if items else None

    def get_by_id(self, decision_id: str, *, principal: str | None = None) -> dict[str, Any] | None:
        """`GET /decisions/{id}` (backend phase-01 §6). `decision_id` is a
        freshly minted ULID (`agents/src/iam_sentinel_agents/prime/
        post_turn.py::decision_id = new_ulid()`), independent of
        `correlation_id` -- so the table's one GSI (`correlation-index`,
        keyed on `correlation_id`) cannot serve this lookup, and no GSI is
        keyed on `decision_id` at all. When `principal` is known (the
        caller's own decisions -- the common case), this queries that one
        partition and filters in-page, which is a real `Query`. Without it
        (an Auditor looking up an arbitrary principal's decision), this
        falls back to a bounded `Scan` -- correct, not O(1); add a
        `decision_id` GSI in a future phase if that path sees real traffic.
        """
        exclusive_start_key: dict[str, Any] | None = None
        for _ in range(_MAX_SCAN_PAGES):
            if principal is not None:
                items, exclusive_start_key = self._helper.query_page(
                    key_condition_expression="#pk = :pk",
                    expression_attribute_values={":pk": principal, ":did": decision_id},
                    expression_attribute_names={"#pk": _PK_ATTR},
                    filter_expression="decision_id = :did",
                    limit=100,
                    exclusive_start_key=exclusive_start_key,
                )
            else:
                items, exclusive_start_key = self._helper.scan_page(
                    filter_expression="decision_id = :did",
                    expression_attribute_values={":did": decision_id},
                    limit=100,
                    exclusive_start_key=exclusive_start_key,
                )
            if items:
                return items[0]
            if exclusive_start_key is None:
                break
        return None
