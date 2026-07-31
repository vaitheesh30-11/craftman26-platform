"""`repair.corrupted_memory` (agents phase-17 §7). §12 Test Plan: "inject
a corrupt memory item; run repair; verify re-derivation."
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from iam_sentinel_agents.repair.corrupted_memory import (
    corrupted_memory_repair,
    MemoryRepairError,
    repair_corrupted_memory,
)

pytestmark = pytest.mark.unit


def test_episodic_repair_re_derives_from_decisions_and_rewrites_memory() -> None:
    decisions_client = MagicMock()
    decisions_client.get_by_correlation_id.return_value = {
        "principal": "arn:aws:iam::111111111111:role/auditor",
        "decided_at": "2026-07-31T00:00:00Z",
        "decision_id": "01DECISION",
        "correlation_id": "01CORRUPT",
    }
    memory_client = MagicMock()
    evidence_client = MagicMock()
    faults_client = MagicMock()

    result = repair_corrupted_memory(
        memory_kind="episodic",
        key={"principal": "arn:aws:iam::111111111111:role/auditor"},
        correlation_id="01CORRUPT",
        decisions_client=decisions_client,
        memory_client=memory_client,
        evidence_client=evidence_client,
        faults_client=faults_client,
    )

    memory_client.remember_episodic.assert_called_once()
    assert result["kind"] == "episodic"
    evidence_client.put_signed_evidence.assert_called_once()
    assert evidence_client.put_signed_evidence.call_args.kwargs["kind"] == "repair_action"
    faults_client.put.assert_called_once()
    assert faults_client.put.call_args.args[0]["action_taken"] == "auto_repaired"


def test_episodic_repair_raises_when_source_of_truth_is_gone() -> None:
    decisions_client = MagicMock()
    decisions_client.get_by_correlation_id.return_value = None

    with pytest.raises(MemoryRepairError):
        repair_corrupted_memory(
            memory_kind="episodic",
            key={"principal": "arn:aws:iam::111111111111:role/auditor"},
            correlation_id="01GONE",
            decisions_client=decisions_client,
            memory_client=MagicMock(),
            evidence_client=MagicMock(),
            faults_client=MagicMock(),
        )


def test_semantic_repair_calls_the_injected_resync_and_upserts() -> None:
    memory_client = MagicMock()
    evidence_client = MagicMock()
    resync = MagicMock(return_value={"entity_kind": "policy", "entity_key": "p-123"})

    result = repair_corrupted_memory(
        memory_kind="semantic",
        key={"entity_kind": "policy", "entity_key": "p-123"},
        correlation_id="01SEMANTIC",
        resync=resync,
        memory_client=memory_client,
        evidence_client=evidence_client,
        faults_client=MagicMock(),
    )

    resync.assert_called_once_with("policy", "p-123")
    memory_client.upsert_semantic.assert_called_once_with(
        {"entity_kind": "policy", "entity_key": "p-123"}
    )
    assert result["kind"] == "semantic"


def test_semantic_repair_without_resync_raises() -> None:
    with pytest.raises(MemoryRepairError):
        repair_corrupted_memory(
            memory_kind="semantic",
            key={"entity_kind": "policy", "entity_key": "p-123"},
            correlation_id="01NORESYNC",
            memory_client=MagicMock(),
            evidence_client=MagicMock(),
            faults_client=MagicMock(),
        )


def test_procedural_repair_invalidates_the_cache_entry() -> None:
    memory_client = MagicMock()
    evidence_client = MagicMock()

    result = repair_corrupted_memory(
        memory_kind="procedural",
        key={"pattern_kind": "scan", "pattern_hash": "abc123"},
        correlation_id="01PROCEDURAL",
        memory_client=memory_client,
        evidence_client=evidence_client,
        faults_client=MagicMock(),
    )

    memory_client.invalidate_procedural.assert_called_once_with("scan", "abc123")
    assert result["result"] == {"invalidated": True}


def test_corrupted_memory_repair_lambda_entrypoint_dispatches_from_event() -> None:
    decisions_client = MagicMock()
    decisions_client.get_by_correlation_id.return_value = {
        "principal": "arn:aws:iam::111111111111:role/auditor",
        "decided_at": "2026-07-31T00:00:00Z",
    }
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(
            "iam_sentinel_agents.repair.corrupted_memory.DecisionsClient",
            lambda: decisions_client,
        )
        mp.setattr("iam_sentinel_agents.repair.corrupted_memory.MemoryClient", lambda: MagicMock())
        mp.setattr(
            "iam_sentinel_agents.repair.corrupted_memory.EvidenceClient", lambda: MagicMock()
        )
        mp.setattr("iam_sentinel_agents.tools.common.retry.FaultsClient", lambda: MagicMock())
        result = corrupted_memory_repair(
            {
                "memory_kind": "episodic",
                "key": {"principal": "arn:aws:iam::111111111111:role/auditor"},
                "correlation_id": "01LAMBDA",
            },
            None,
        )

    assert result["kind"] == "episodic"
