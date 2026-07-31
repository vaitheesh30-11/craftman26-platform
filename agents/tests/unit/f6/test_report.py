"""phase-07 §4 Step 4-5, pure aggregation/CDK-generation path -- no DDB/S3."""

from __future__ import annotations

from datetime import datetime, UTC

import pytest

from iam_sentinel_agents.contracts.shadow_guard import ShadowViolation
from iam_sentinel_agents.tools.f6.report import build_report, compensating_controls_for

pytestmark = pytest.mark.unit


def _violation(
    action: str, severity: str, *, event_time: datetime | None = None
) -> ShadowViolation:
    return ShadowViolation(
        action=action,
        principal_arn="arn:aws:iam::111122223333:user/RootOps",
        principal_type="IAMUser",
        would_be_denied_by_scp_arn="arn:aws:organizations::o-1:policy/p-root-deny",
        denying_statement_id="DenyIt",
        would_be_denied_at_level="root",
        event_id="evt-1",
        event_time=event_time or datetime(2026, 7, 27, tzinfo=UTC),
        severity=severity,
    )


def test_severity_filter_excludes_findings_below_threshold() -> None:
    violations = [
        _violation("organizations:deletepolicy", "CRITICAL"),
        _violation("s3:deleteobject", "MEDIUM"),
    ]

    payload, _ = build_report(
        violations, days_back=7, severity_filter="HIGH", total_events_ingested=100
    )

    assert payload.violation_count == 1
    assert payload.violations[0].action == "organizations:deletepolicy"


def test_top_actions_counts_and_orders_by_frequency() -> None:
    violations = [
        _violation("iam:deleterole", "HIGH"),
        _violation("iam:deleterole", "HIGH"),
        _violation("organizations:deletepolicy", "CRITICAL"),
    ]

    payload, _ = build_report(
        violations, days_back=7, severity_filter="MEDIUM", total_events_ingested=10
    )

    assert payload.top_actions[0]["action"] == "iam:deleterole"
    assert payload.top_actions[0]["count"] == 2


def test_empty_violations_yields_clean_confirm_shaped_payload() -> None:
    payload, controls = build_report(
        [], days_back=7, severity_filter="MEDIUM", total_events_ingested=500
    )

    assert payload.violation_count == 0
    assert payload.violations == []
    assert controls == []


def test_compensating_controls_include_an_eventbridge_and_a_configrule_for_the_top_action() -> None:
    violations = [_violation("organizations:deletepolicy", "CRITICAL") for _ in range(3)]
    payload, _ = build_report(
        violations, days_back=7, severity_filter="MEDIUM", total_events_ingested=10
    )

    controls = compensating_controls_for(payload)

    kinds = {c.control_kind for c in controls}
    assert kinds == {"EventBridgeRule", "ConfigRule"}
    assert all(
        "organizations:deletepolicy" in c.cdk_snippet.lower()
        or "deletepolicy" in c.cdk_snippet.lower()
        for c in controls
    )
