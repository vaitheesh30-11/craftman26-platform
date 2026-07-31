"""Hypothesis-driven round-trip fuzzing — ≥500 examples per model.

Per phase-00 acceptance criteria. Composite strategies for Finding and
RemediationPlan satisfy their cross-field invariants by construction (see
_strategies.py), so every generated example is guaranteed valid — no
`.filter()`, no `filter_too_much` health-check risk.
"""

from __future__ import annotations

import pytest
from hypothesis import given, HealthCheck, settings

from tests.contract._strategies import (
    aws_doc_citations,
    episodic_memories,
    evidence_refs,
    findings,
    procedural_hits,
    recall_results,
    remediation_plans,
    semantic_entities,
    tool_invocations,
    untrusted_context_blocks,
    zelkova_checks,
)

pytestmark = pytest.mark.contract

_SETTINGS = settings(
    max_examples=500,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


@_SETTINGS
@given(citation=aws_doc_citations())
def test_aws_doc_citation_roundtrip(citation) -> None:
    restored = type(citation).model_validate_json(citation.model_dump_json(by_alias=True))
    assert restored == citation


@_SETTINGS
@given(ref=evidence_refs())
def test_evidence_ref_roundtrip(ref) -> None:
    restored = type(ref).model_validate_json(ref.model_dump_json(by_alias=True))
    assert restored == ref


@_SETTINGS
@given(check=zelkova_checks())
def test_zelkova_check_roundtrip(check) -> None:
    restored = type(check).model_validate_json(check.model_dump_json(by_alias=True))
    assert restored == check


@_SETTINGS
@given(invocation=tool_invocations())
def test_tool_invocation_roundtrip(invocation) -> None:
    restored = type(invocation).model_validate_json(invocation.model_dump_json(by_alias=True))
    assert restored == invocation


@_SETTINGS
@given(block=untrusted_context_blocks())
def test_untrusted_context_block_roundtrip(block) -> None:
    restored = type(block).model_validate_json(block.model_dump_json(by_alias=True))
    assert restored == block


@_SETTINGS
@given(finding=findings())
def test_finding_roundtrip(finding) -> None:
    restored = type(finding).model_validate_json(finding.model_dump_json(by_alias=True))
    assert restored == finding


@_SETTINGS
@given(plan=remediation_plans())
def test_remediation_plan_roundtrip(plan) -> None:
    restored = type(plan).model_validate_json(plan.model_dump_json(by_alias=True))
    assert restored == plan


@_SETTINGS
@given(record=episodic_memories())
def test_episodic_memory_roundtrip(record) -> None:
    restored = type(record).model_validate_json(record.model_dump_json(by_alias=True))
    assert restored == record


@_SETTINGS
@given(entity=semantic_entities())
def test_semantic_entity_roundtrip(entity) -> None:
    restored = type(entity).model_validate_json(entity.model_dump_json(by_alias=True))
    assert restored == entity


@_SETTINGS
@given(hit=procedural_hits())
def test_procedural_hit_roundtrip(hit) -> None:
    restored = type(hit).model_validate_json(hit.model_dump_json(by_alias=True))
    assert restored == hit


@_SETTINGS
@given(result=recall_results())
def test_recall_result_roundtrip(result) -> None:
    restored = type(result).model_validate_json(result.model_dump_json(by_alias=True))
    assert restored == result
