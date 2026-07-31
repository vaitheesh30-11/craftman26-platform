"""Schema/quality gate for `agents/evals/self_healing/golden.jsonl` (agents
phase-17 §12 Test Plan). Self-healing is not a Bedrock-callable specialist
(there is no Prime turn to run these scenarios against), so unlike the F1-
F8 golden sets, this file is validated for internal consistency against
this phase's own real, deterministic logic (`ADAPTER_CALL_SITE_POLICY`,
`FALLBACK_SPECS`, the watchdog threshold table, the drift classifier)
rather than schema-only field presence -- a stronger gate than the F1-F8
precedent affords, since nothing here depends on a not-yet-existing
`iam_sentinel_agents.evals.runner` (phase-12) or a deployed agent.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from iam_sentinel_adapters.retry import Policy

from iam_sentinel_agents.drift.detector import _is_auto_repairable, _is_never_remediate
from iam_sentinel_agents.tools.common.fallback import FALLBACK_SPECS
from iam_sentinel_agents.tools.common.retry import ADAPTER_CALL_SITE_POLICY
from iam_sentinel_agents.watchdog.scanner import _EXTENDED_STUCK_FEATURES, _stuck_threshold

pytestmark = pytest.mark.unit

GOLDEN_PATH = Path(__file__).resolve().parents[2] / "evals" / "self_healing" / "golden.jsonl"

_REQUIRED_CATEGORIES = {
    "retry-recoverable",
    "escalation-required",
    "fallback-required",
    "no-fallback-escalation",
    "watchdog-rescue",
    "watchdog-extended-threshold",
    "auto-repairable-drift",
    "never-auto-remediate-drift",
}
_REQUIRED_FIELDS = {"id", "category", "scenario", "fault_class", "notes"}
_VALID_FAULT_CLASSES = {
    "transient_throttling",
    "transient_network",
    "eventual_consistency",
    "adapter_fault",
    "model_fault",
    "logic_fault",
    "infra_drift",
    "data_corruption",
    "region_outage",
}


def _load_golden() -> list[dict[str, Any]]:
    lines = GOLDEN_PATH.read_text(encoding="utf-8").strip().splitlines()
    return [json.loads(line) for line in lines]


def test_golden_file_exists_and_has_at_least_five_entries() -> None:
    assert len(_load_golden()) >= 5


def test_every_entry_has_required_fields_and_a_valid_fault_class() -> None:
    for entry in _load_golden():
        missing = _REQUIRED_FIELDS - entry.keys()
        assert not missing, f"{entry.get('id')} missing {missing}"
        assert entry["fault_class"] in _VALID_FAULT_CLASSES, entry["id"]


def test_every_required_category_has_at_least_one_entry() -> None:
    categories = {entry["category"] for entry in _load_golden()}
    missing = _REQUIRED_CATEGORIES - categories
    assert not missing, f"missing golden-set coverage for: {missing}"


def test_ids_are_unique() -> None:
    ids = [entry["id"] for entry in _load_golden()]
    assert len(ids) == len(set(ids))


def test_retry_recoverable_entries_match_the_real_call_site_policy_table() -> None:
    for entry in _load_golden():
        if entry["category"] != "retry-recoverable":
            continue
        policy, fault_class = ADAPTER_CALL_SITE_POLICY[entry["call_site"]]
        assert policy is Policy[entry["expected_policy"]]
        assert fault_class == entry["fault_class"]


def test_escalation_entries_are_assigned_the_none_policy() -> None:
    for entry in _load_golden():
        if entry["category"] != "escalation-required":
            continue
        policy, _fault_class = ADAPTER_CALL_SITE_POLICY[entry["call_site"]]
        assert policy is Policy.NONE


def test_fallback_entries_match_the_real_fallback_spec_table() -> None:
    for entry in _load_golden():
        if entry["category"] not in {"fallback-required", "no-fallback-escalation"}:
            continue
        spec = FALLBACK_SPECS[entry["feature_id"]]
        assert spec.action == entry["expected_fallback_action"]
        if entry["category"] == "no-fallback-escalation":
            assert spec.has_fast_path is False
        else:
            assert spec.has_fast_path is True


def test_watchdog_entries_match_the_real_stuck_threshold_table() -> None:
    thresholds = {
        "sh-watchdog-01": ("F1", 5),
        "sh-watchdog-02": ("F4", 10),
    }
    for _entry_id, (feature_id, expected_minutes) in thresholds.items():
        assert _stuck_threshold(feature_id).total_seconds() == expected_minutes * 60
    assert "F4" in _EXTENDED_STUCK_FEATURES
    assert "F1" not in _EXTENDED_STUCK_FEATURES


def test_drift_entries_match_the_real_classifier() -> None:
    classifiers = {
        "sh-drift-01": ("AuditorReadOnlyPolicy", "AWS::IAM::Policy", "auto_repaired"),
        "sh-drift-02": ("EvidenceKmsKey", "AWS::KMS::Key", "paged"),
    }
    for _entry_id, (logical_id, resource_type, expected) in classifiers.items():
        if _is_never_remediate(logical_id, resource_type):
            classification = "paged"
        elif _is_auto_repairable(resource_type):
            classification = "auto_repaired"
        else:
            classification = "paged"
        assert classification == expected
