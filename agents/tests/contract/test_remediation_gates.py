"""RemediationPlan and SpecialistVerdict enforce Zelkova pre-check contracts."""

from __future__ import annotations

from datetime import datetime, UTC

import pytest
from pydantic import ValidationError

from iam_sentinel_agents.contracts import RemediationPlan, SpecialistVerdict, ZelkovaCheck
from tests.contract._factories import (
    make_finding,
    make_tool_invocation,
    make_verdict,
    make_zelkova_pass,
    SHA256_ONES,
    SHA256_TWOS,
    VALID_ROLE_ARN,
)

pytestmark = pytest.mark.contract

NOW = datetime(2026, 7, 30, 12, 0, 0, tzinfo=UTC)


def _zelkova(*, passed: bool) -> ZelkovaCheck:
    return ZelkovaCheck(
        **{"pass": passed},
        witness=None if passed else "principal.can:s3:PutBucketPolicy",
        latency_ms=42,
        invoked_at=NOW,
        baseline_hash=SHA256_ONES,
        candidate_hash=SHA256_TWOS,
    )


def test_apply_without_pre_check_rejected() -> None:
    with pytest.raises(ValidationError, match="zelkova_pre to be present"):
        RemediationPlan(
            action="attach_inline_policy",
            target_arn=VALID_ROLE_ARN,
            policy_document={"Version": "2012-10-17", "Statement": []},
            dry_run=False,
        )


def test_apply_with_failing_pre_check_rejected() -> None:
    with pytest.raises(ValidationError, match=r"zelkova_pre\.pass=True"):
        RemediationPlan(
            action="attach_inline_policy",
            target_arn=VALID_ROLE_ARN,
            policy_document={"Version": "2012-10-17", "Statement": []},
            dry_run=False,
            zelkova_pre=_zelkova(passed=False),
        )


def test_apply_with_passing_pre_check_accepted() -> None:
    plan = RemediationPlan(
        action="attach_inline_policy",
        target_arn=VALID_ROLE_ARN,
        policy_document={"Version": "2012-10-17", "Statement": []},
        dry_run=False,
        zelkova_pre=_zelkova(passed=True),
    )
    assert plan.zelkova_pre is not None
    assert plan.zelkova_pre.pass_ is True


def test_verdict_confirm_with_mutation_requires_passing_zelkova() -> None:
    with pytest.raises(ValidationError, match="passing Zelkova check"):
        SpecialistVerdict(
            correlation_id="01JBP2VHF9K3Q0Z8R7X6M5N4A3",
            feature_id="F1",
            verdict="CONFIRM",
            reason="applying policy",
            findings=[make_finding()],
            remediation=RemediationPlan(
                action="attach_inline_policy",
                target_arn=VALID_ROLE_ARN,
                policy_document={"Version": "2012-10-17", "Statement": []},
                dry_run=False,
                zelkova_pre=make_zelkova_pass(),
            ),
            tool_invocations=[make_tool_invocation(with_zelkova=False)],
            duration_ms=1234,
        )


def test_verdict_confirm_with_dry_run_allowed_without_zelkova() -> None:
    verdict = make_verdict()
    assert verdict.verdict == "CONFIRM"
    assert verdict.remediation is None
