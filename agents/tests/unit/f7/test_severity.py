from __future__ import annotations

import pytest

from iam_sentinel_agents.tools.f7.severity import compute_collision_severity

pytestmark = pytest.mark.unit


def test_defaults_to_medium_with_no_supporting_data() -> None:
    severity, reason = compute_collision_severity("ec2:RunInstances")
    assert severity == "MEDIUM"
    assert reason is None


def test_high_volume_historical_calls_escalates_to_high() -> None:
    severity, reason = compute_collision_severity("ec2:RunInstances", historical_call_count=150)
    assert severity == "HIGH"
    assert reason is None


def test_below_threshold_call_count_stays_medium() -> None:
    severity, _ = compute_collision_severity("ec2:RunInstances", historical_call_count=99)
    assert severity == "MEDIUM"


def test_slr_required_action_with_initialized_db_is_critical() -> None:
    severity, reason = compute_collision_severity(
        "ec2:TerminateInstances",
        slr_db_initialized=True,
        slr_required_actions=frozenset({"ec2:TerminateInstances"}),
    )
    assert severity == "CRITICAL"
    assert reason is None


def test_slr_required_action_with_uninitialized_db_degrades_to_high() -> None:
    severity, reason = compute_collision_severity(
        "ec2:TerminateInstances",
        slr_db_initialized=False,
        slr_required_actions=frozenset({"ec2:TerminateInstances"}),
    )
    assert severity == "HIGH"
    assert reason == "SLR DB not yet initialized"


def test_slr_match_is_wildcard_aware() -> None:
    severity, _ = compute_collision_severity(
        "iam:DeleteRole",
        slr_db_initialized=True,
        slr_required_actions=frozenset({"iam:*"}),
    )
    assert severity == "CRITICAL"
