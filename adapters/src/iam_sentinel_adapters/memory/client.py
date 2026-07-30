"""Shared recall/remember interface used by Prime and every specialist
(phase-05 §5). Episodic recall's true semantic path needs OpenSearch
Serverless k-NN search against a live collection (ADR 0005/0006); until
then it degrades to a DDB-only, most-recent-first query on `principal`,
still correct for exact-principal lookups but not similarity search over
`query`. Semantic and procedural memory never needed OSS and are fully
implemented against DDB alone.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from iam_sentinel_adapters.ddb.base import DynamoDbHelper
from iam_sentinel_adapters.settings import settings

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

    from iam_sentinel_adapters.circuit_breaker import BreakerAccessor


class MemoryClient:
    def __init__(
        self,
        *,
        episodic_table: Table | None = None,
        semantic_table: Table | None = None,
        procedural_table: Table | None = None,
        breaker: BreakerAccessor | None = None,
    ) -> None:
        self._episodic = DynamoDbHelper(settings.memory_episodic_table, table=episodic_table, breaker=breaker)
        self._semantic = DynamoDbHelper(settings.memory_semantic_table, table=semantic_table, breaker=breaker)
        self._procedural = DynamoDbHelper(
            settings.memory_procedural_table, table=procedural_table, breaker=breaker
        )

    def remember_episodic(self, record: dict[str, Any], correlation_id: str) -> None:
        self._episodic.put_item({**record, "correlation_id": correlation_id})

    def recall_episodic(
        self, principal: str, query: str | None, top_k: int  # noqa: ARG002 -- see module docstring
    ) -> list[dict[str, Any]]:
        return self._episodic.query(
            key_condition_expression="principal = :principal",
            expression_attribute_values={":principal": principal},
            limit=top_k,
            scan_index_forward=False,
        )

    def upsert_semantic(self, entity: dict[str, Any]) -> bool:
        existing = self._semantic.get_item(
            {"entity_kind": entity["entity_kind"], "entity_key": entity["entity_key"]}
        )
        if existing is not None and _canonical(existing) == _canonical(entity):
            return False
        self._semantic.put_item(entity)
        return True

    def recall_semantic(self, kind: str, facet: dict[str, Any]) -> list[dict[str, Any]]:
        items = self._semantic.query(
            key_condition_expression="entity_kind = :kind",
            expression_attribute_values={":kind": kind},
        )
        if not facet:
            return items
        return [item for item in items if all(item.get(k) == v for k, v in facet.items())]

    def procedural_get(self, pattern_kind: str, pattern_hash: str) -> dict[str, Any] | None:
        return self._procedural.get_item({"pattern_kind": pattern_kind, "pattern_hash": pattern_hash})

    def procedural_put(
        self, pattern_kind: str, pattern_hash: str, result: dict[str, Any], ttl_seconds: int
    ) -> None:
        expires_at = int(datetime.now(UTC).timestamp()) + ttl_seconds
        self._procedural.put_item(
            {
                "pattern_kind": pattern_kind,
                "pattern_hash": pattern_hash,
                "result": result,
                "expires_at": expires_at,
            }
        )


def _canonical(item: dict[str, Any]) -> str:
    comparable = {k: v for k, v in item.items() if k not in ("entity_kind", "entity_key")}
    return json.dumps(comparable, sort_keys=True, default=str)
