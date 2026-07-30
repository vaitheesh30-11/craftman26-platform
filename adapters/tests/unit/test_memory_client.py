from __future__ import annotations

from typing import TYPE_CHECKING

from iam_sentinel_adapters.memory.client import MemoryClient

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

    from iam_sentinel_adapters.circuit_breaker import BreakerAccessor


def _client(
    memory_episodic_table: Table,
    memory_semantic_table: Table,
    memory_procedural_table: Table,
    moto_breaker: BreakerAccessor,
) -> MemoryClient:
    return MemoryClient(
        episodic_table=memory_episodic_table,
        semantic_table=memory_semantic_table,
        procedural_table=memory_procedural_table,
        breaker=moto_breaker,
    )


def test_remember_then_recall_episodic(
    memory_episodic_table: Table,
    memory_semantic_table: Table,
    memory_procedural_table: Table,
    moto_breaker: BreakerAccessor,
) -> None:
    client = _client(memory_episodic_table, memory_semantic_table, memory_procedural_table, moto_breaker)

    client.remember_episodic(
        {"principal": "alice", "decided_at": "2026-07-30T00:00:00+00:00", "verdict": "CONFIRM"},
        correlation_id="corr-1",
    )

    results = client.recall_episodic("alice", query=None, top_k=10)
    assert len(results) == 1
    assert results[0]["verdict"] == "CONFIRM"


def test_upsert_semantic_reports_change_then_no_change(
    memory_episodic_table: Table,
    memory_semantic_table: Table,
    memory_procedural_table: Table,
    moto_breaker: BreakerAccessor,
) -> None:
    client = _client(memory_episodic_table, memory_semantic_table, memory_procedural_table, moto_breaker)
    entity = {"entity_kind": "role", "entity_key": "arn:aws:iam::111122223333:role/X", "tags": ["prod"]}

    assert client.upsert_semantic(entity) is True
    assert client.upsert_semantic(entity) is False
    assert client.upsert_semantic({**entity, "tags": ["prod", "critical"]}) is True


def test_recall_semantic_filters_by_facet(
    memory_episodic_table: Table,
    memory_semantic_table: Table,
    memory_procedural_table: Table,
    moto_breaker: BreakerAccessor,
) -> None:
    client = _client(memory_episodic_table, memory_semantic_table, memory_procedural_table, moto_breaker)
    client.upsert_semantic({"entity_kind": "role", "entity_key": "a", "env": "prod"})
    client.upsert_semantic({"entity_kind": "role", "entity_key": "b", "env": "dev"})

    results = client.recall_semantic("role", {"env": "prod"})

    assert [r["entity_key"] for r in results] == ["a"]


def test_procedural_put_then_get_round_trips(
    memory_episodic_table: Table,
    memory_semantic_table: Table,
    memory_procedural_table: Table,
    moto_breaker: BreakerAccessor,
) -> None:
    client = _client(memory_episodic_table, memory_semantic_table, memory_procedural_table, moto_breaker)

    client.procedural_put("scp_shape", "hash123", {"verdict": "REMEDIATE"}, ttl_seconds=3600)

    hit = client.procedural_get("scp_shape", "hash123")
    assert hit is not None
    assert hit["result"]["verdict"] == "REMEDIATE"


def test_procedural_get_missing_returns_none(
    memory_episodic_table: Table,
    memory_semantic_table: Table,
    memory_procedural_table: Table,
    moto_breaker: BreakerAccessor,
) -> None:
    client = _client(memory_episodic_table, memory_semantic_table, memory_procedural_table, moto_breaker)

    assert client.procedural_get("scp_shape", "missing") is None
