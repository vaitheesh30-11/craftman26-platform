"""Unit tests for `tools/memory/recall.py` and `tools/memory/remember.py`
(phase-14 §7 Test Plan: episodic/semantic/procedural round trip; isolation
property "attempt to recall episodic memory for principal A while invoking
as principal B; must fail closed").
"""

from __future__ import annotations

from datetime import datetime, UTC

import pytest
from moto import mock_aws

from iam_sentinel_agents.contracts.evidence import EvidenceRef
from iam_sentinel_agents.contracts.memory import EpisodicMemory, SemanticEntity
from iam_sentinel_agents.errors import MemoryIsolationError, MemoryWriteForbiddenError
from iam_sentinel_agents.tools.memory import recall, remember
from tests.unit.memory import _ddb

pytestmark = pytest.mark.unit

_PRINCIPAL_A = "arn:aws:iam::111122223333:user/alice"
_PRINCIPAL_B = "arn:aws:iam::111122223333:user/bob"


def _evidence_ref() -> EvidenceRef:
    return EvidenceRef(
        bucket="sentinel-evidence-dev",
        key="f1/2026/07/31/decision.json",
        version_id="v1",
        kms_key_arn="arn:aws:kms:us-east-1:111122223333:key/abc-123",
        signature="sig",
        sha256="a" * 64,
        stored_at=datetime(2026, 7, 31, tzinfo=UTC),
    )


def _episodic_memory(principal: str = _PRINCIPAL_A) -> EpisodicMemory:
    return EpisodicMemory(
        principal=principal,
        decision_id="01JBP2VHF9K3Q0Z8R7X6M5N4A1",
        correlation_id="01JBP2VHF9K3Q0Z8R7X6M5N4A2",
        feature_ids_involved=["F1"],
        finding_summary="HIGH: PassRole blast radius",
        narrative_excerpt="Alice can pass a privileged role.",
        evidence_ref=_evidence_ref(),
        tags={"account_id": "111122223333"},
        decided_at=datetime(2026, 7, 31, tzinfo=UTC),
    )


@mock_aws
def test_remember_episodic_then_recall_returns_it() -> None:
    memory = _ddb.memory_client()
    record = _episodic_memory()

    remember.remember_episodic(
        memory, record, invoking_principal=_PRINCIPAL_A, writer_role="prime_post_turn"
    )
    result = recall.recall_episodic(memory, invoking_principal=_PRINCIPAL_A, top_k=5)

    assert result.kind == "episodic"
    assert result.total_scanned == 1
    assert result.hits[0]["decision_id"] == record.decision_id


@mock_aws
def test_recall_episodic_for_other_principal_fails_closed() -> None:
    memory = _ddb.memory_client()
    remember.remember_episodic(
        memory, _episodic_memory(_PRINCIPAL_A), invoking_principal=_PRINCIPAL_A, writer_role="prime_post_turn"
    )

    with pytest.raises(MemoryIsolationError):
        recall.recall_episodic(
            memory,
            invoking_principal=_PRINCIPAL_B,
            target_principal=_PRINCIPAL_A,
            top_k=5,
        )


@mock_aws
def test_recall_episodic_with_empty_invoking_principal_fails_closed() -> None:
    memory = _ddb.memory_client()
    with pytest.raises(MemoryIsolationError):
        recall.recall_episodic(memory, invoking_principal="", top_k=5)


@mock_aws
def test_remember_episodic_rejects_wrong_writer_role() -> None:
    memory = _ddb.memory_client()
    with pytest.raises(MemoryWriteForbiddenError):
        remember.remember_episodic(
            memory, _episodic_memory(), invoking_principal=_PRINCIPAL_A, writer_role="some_specialist"
        )


@mock_aws
def test_remember_episodic_rejects_principal_mismatch_between_record_and_caller() -> None:
    memory = _ddb.memory_client()
    with pytest.raises(MemoryIsolationError):
        remember.remember_episodic(
            memory,
            _episodic_memory(_PRINCIPAL_B),
            invoking_principal=_PRINCIPAL_A,
            writer_role="prime_post_turn",
        )


@mock_aws
def test_upsert_semantic_then_recall_by_facet() -> None:
    memory = _ddb.memory_client()
    entity = SemanticEntity(
        entity_kind="role",
        entity_key="arn:aws:iam::111122223333:role/prod-admin",
        body={"env": "prod"},
        synced_at=datetime(2026, 7, 31, tzinfo=UTC),
        source_of_truth="iam:ListRoles",
        related_entities=[],
        body_sha256="b" * 64,
    )

    changed = remember.upsert_semantic(memory, entity, writer_role="semantic_syncer")
    result = recall.recall_semantic(memory, entity_kind="role", facet={"entity_key": entity.entity_key})

    assert changed is True
    assert result.total_scanned == 1


@mock_aws
def test_upsert_semantic_rejects_wrong_writer_role() -> None:
    memory = _ddb.memory_client()
    entity = SemanticEntity(
        entity_kind="role",
        entity_key="x",
        body={},
        synced_at=datetime(2026, 7, 31, tzinfo=UTC),
        source_of_truth="iam:ListRoles",
        related_entities=[],
        body_sha256="c" * 64,
    )
    with pytest.raises(MemoryWriteForbiddenError):
        remember.upsert_semantic(memory, entity, writer_role="prime_post_turn")


@mock_aws
def test_remember_procedural_then_recall_hit() -> None:
    memory = _ddb.memory_client()
    remember.remember_procedural(
        memory,
        pattern_kind="scp_effective_policy",
        pattern_hash="d" * 64,
        result={"allowed": ["s3:GetObject"]},
        ttl_seconds=900,
        writer_role="tool_memoizer",
    )
    result = recall.recall_procedural(memory, pattern_kind="scp_effective_policy", pattern_hash="d" * 64)

    assert result.total_scanned == 1
    assert result.hits[0]["result"]["allowed"] == ["s3:GetObject"]


@mock_aws
def test_recall_procedural_miss_returns_empty_hits() -> None:
    memory = _ddb.memory_client()
    result = recall.recall_procedural(memory, pattern_kind="scp_effective_policy", pattern_hash="e" * 64)
    assert result.hits == []
    assert result.total_scanned == 0


@mock_aws
def test_remember_procedural_rejects_wrong_writer_role() -> None:
    memory = _ddb.memory_client()
    with pytest.raises(MemoryWriteForbiddenError):
        remember.remember_procedural(
            memory,
            pattern_kind="scp_effective_policy",
            pattern_hash="f" * 64,
            result={},
            ttl_seconds=900,
            writer_role="prime_post_turn",
        )
