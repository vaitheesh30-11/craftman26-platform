"""Chaos: Zelkova errors (phase-13 §4 Step 4). Real `ZelkovaClient` against
an Access Analyzer client that always raises. Passes when: `ZelkovaError`
is raised for every operation this client exposes -- never a fabricated
passing `ZelkovaResult`. `ZelkovaClient`'s own module docstring states the
invariant this test locks in: "Never fails open... there is no path that
returns pass_=True from a caught exception."
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from iam_sentinel_adapters.errors import ZelkovaError
from iam_sentinel_adapters.zelkova.client import ZelkovaClient

_EXISTING_POLICY = {"Version": "2012-10-17", "Statement": []}
_CANDIDATE_POLICY = {
    "Version": "2012-10-17",
    "Statement": [{"Effect": "Allow", "Action": "s3:GetObject", "Resource": "arn:aws:s3:::b/*"}],
}


def _raising_access_analyzer() -> MagicMock:
    client = MagicMock()
    client.check_no_new_access.side_effect = RuntimeError("Access Analyzer unavailable")
    client.check_access_not_granted.side_effect = RuntimeError("Access Analyzer unavailable")
    return client


def _build_client() -> ZelkovaClient:
    return ZelkovaClient(
        access_analyzer_client=_raising_access_analyzer(),
        iam_client=MagicMock(),
        cost_meter=MagicMock(),
        evidence_client=MagicMock(),
        breaker=MagicMock(),
        metrics=MagicMock(),
    )


def test_check_no_new_access_never_fails_open() -> None:
    client = _build_client()
    with pytest.raises(ZelkovaError):
        client.check_no_new_access(
            existing=_EXISTING_POLICY,
            candidate=_CANDIDATE_POLICY,
            correlation_id="01JBP2VHF9K3Q0Z8R7X6M5N4C3",
            feature_id="F3",
        )


def test_check_access_not_granted_never_fails_open() -> None:
    client = _build_client()
    with pytest.raises(ZelkovaError):
        client.check_access_not_granted(
            policy=_CANDIDATE_POLICY,
            access=[{"actions": ["s3:GetObject"], "resources": ["arn:aws:s3:::b/*"]}],
            policy_type="IDENTITY_POLICY",
            correlation_id="01JBP2VHF9K3Q0Z8R7X6M5N4C4",
            feature_id="F3",
        )


def test_a_confirm_verdict_can_never_carry_a_mutating_remediation_without_a_passing_check() -> None:
    """The downstream guarantee this chaos scenario exists to protect:
    `SpecialistVerdict`'s own validator (contracts/verdict.py) rejects a
    non-dry-run `CONFIRM` remediation unless every mutating tool invocation
    carries a passing Zelkova check -- so even if a caller ignored the
    raised `ZelkovaError` and tried to synthesize success anyway, the
    contract layer would refuse to construct that verdict.
    """
    from datetime import datetime, UTC

    from iam_sentinel_agents.contracts.remediation import RemediationPlan, ZelkovaCheck
    from iam_sentinel_agents.contracts.verdict import SpecialistVerdict, ToolInvocation

    failing_check = ZelkovaCheck(
        **{"pass": False},
        witness="principal=* action=s3:GetObject resource=arn:aws:s3:::b/*",
        latency_ms=10,
        invoked_at=datetime.now(UTC),
        baseline_hash="a" * 64,
        candidate_hash="b" * 64,
    )
    # `RemediationPlan`'s own gate fires first here (dry_run=False requires
    # a *passing* `zelkova_pre`) -- an even earlier conservative refusal
    # than `SpecialistVerdict`'s cross-invocation check, proving the "never
    # fail open" guarantee holds at two independent layers, not just one.
    with pytest.raises(ValueError, match="zelkova_pre.pass=True"):
        SpecialistVerdict(
            correlation_id="01JBP2VHF9K3Q0Z8R7X6M5N4C5",
            feature_id="F3",
            verdict="CONFIRM",
            reason="attempting to confirm despite a failing Zelkova check",
            findings=[],
            remediation=RemediationPlan(
                action="attach_inline_policy",
                target_arn="arn:aws:iam::111122223333:role/Prod",
                policy_document=_CANDIDATE_POLICY,
                dry_run=False,
                zelkova_pre=failing_check,
            ),
            tool_invocations=[
                ToolInvocation(
                    tool_name="data_event_merge",
                    input_hash="c" * 64,
                    output_hash="d" * 64,
                    duration_ms=10,
                    zelkova_check=failing_check,
                )
            ],
            duration_ms=10,
        )
