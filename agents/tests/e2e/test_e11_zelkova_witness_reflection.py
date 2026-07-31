"""E-11 — Zelkova witness on an F3 merge, reflection loop (phase-13
scenario table). Real `ZelkovaClient._run_check` (via `check_no_new_access`)
against a fake Access Analyzer client that fails twice with a witness then
passes on the third attempt -- proving the *evidence and contract* half of
"two retries with witness in `prior_failure_witness`, then ESCALATE if
still failing" for real: `ZelkovaResult.witness` is populated from a real
(fake-backed, not fabricated) Access Analyzer response, and
`decision_composer` correctly escalates a verdict that never got a
passing check.

The retry *loop itself* -- the specialist prompt re-attempting F3's merge
with the prior witness fed back as `prior_failure_witness` -- is Bedrock
model/prompt behavior, not Python (docs/decisions/0013 Gap 2 precedent).
This test does not fabricate that loop as Python code; it proves the two
things that are real: witness capture, and composer escalation when a
verdict still lacks a passing Zelkova check after retries are exhausted.
"""

from __future__ import annotations

from datetime import datetime, UTC
from unittest.mock import MagicMock

import pytest
from iam_sentinel_adapters.errors import ZelkovaError
from iam_sentinel_adapters.zelkova.client import ZelkovaClient

from iam_sentinel_agents.contracts.remediation import ZelkovaCheck
from iam_sentinel_agents.contracts.verdict import SpecialistVerdict, ToolInvocation
from iam_sentinel_agents.prime.decision_composer import compose_status

_CORRELATION_ID = "01JBP2VHF9K3Q0Z8R7X6M5N4B5"
_EXISTING_POLICY = {"Version": "2012-10-17", "Statement": []}
_CANDIDATE_POLICY = {
    "Version": "2012-10-17",
    "Statement": [{"Effect": "Allow", "Action": "s3:GetObject", "Resource": "arn:aws:s3:::b/*"}],
}


def _fake_access_analyzer_failing_then_passing() -> MagicMock:
    client = MagicMock()
    client.check_no_new_access.side_effect = [
        {
            "result": "FAIL",
            "reasons": [{"principal": "*", "action": "s3:GetObject", "resource": "arn:aws:s3:::b/*"}],
        },
        {
            "result": "FAIL",
            "reasons": [{"principal": "*", "action": "s3:GetObject", "resource": "arn:aws:s3:::b/*"}],
        },
        {"result": "PASS", "reasons": []},
    ]
    return client


def test_e11_two_failing_checks_carry_a_real_witness_third_check_passes() -> None:
    client = ZelkovaClient(
        access_analyzer_client=_fake_access_analyzer_failing_then_passing(),
        iam_client=MagicMock(),
        cost_meter=MagicMock(),
        evidence_client=MagicMock(),
        breaker=MagicMock(),
        metrics=MagicMock(),
    )
    kwargs = dict(
        existing=_EXISTING_POLICY,
        candidate=_CANDIDATE_POLICY,
        correlation_id=_CORRELATION_ID,
        feature_id="F3",
    )

    attempt_1 = client.check_no_new_access(**kwargs)
    attempt_2 = client.check_no_new_access(**kwargs)
    attempt_3 = client.check_no_new_access(**kwargs)

    assert attempt_1.pass_ is False
    assert attempt_1.witness is not None
    assert attempt_1.witness.action == "s3:GetObject"
    assert attempt_2.pass_ is False
    assert attempt_2.witness is not None
    assert attempt_3.pass_ is True
    assert attempt_3.witness is None


def test_e11_still_failing_after_retries_escalates() -> None:
    """If the reflection loop is exhausted (both retries still FAIL --
    unlike the passing-third-attempt case above), the specialist's verdict
    for this turn must be `ESCALATE`, and the composer must surface that as
    `DecisionRecord.status == "ESCALATED"`, never a fabricated `CONFIRM`.
    """
    verdict = SpecialistVerdict(
        correlation_id=_CORRELATION_ID,
        feature_id="F3",
        verdict="ESCALATE",
        reason="Zelkova CheckNoNewAccess still FAILs after 2 retries; witness unresolved",
        findings=[],
        remediation=None,
        tool_invocations=[
            ToolInvocation(
                tool_name="data_event_merge",
                input_hash="5" * 64,
                output_hash="6" * 64,
                duration_ms=100,
                zelkova_check=ZelkovaCheck(
                    **{"pass": False},
                    witness="principal=* action=s3:GetObject resource=arn:aws:s3:::b/*",
                    latency_ms=50,
                    invoked_at=datetime.now(UTC),
                    baseline_hash="7" * 64,
                    candidate_hash="8" * 64,
                ),
            )
        ],
        duration_ms=100,
    )

    assert compose_status([verdict]) == "ESCALATED"


def test_e11_zelkova_never_returns_pass_true_from_a_caught_exception() -> None:
    """Guardrail against the failure mode the F3 reflection loop depends
    on never happening: `ZelkovaClient` never fails open. A transport/API
    error raises `ZelkovaError`; it is never silently turned into
    `pass_=True`.
    """
    client = ZelkovaClient(
        access_analyzer_client=_raising_access_analyzer(),
        iam_client=MagicMock(),
        cost_meter=MagicMock(),
        evidence_client=MagicMock(),
        breaker=MagicMock(),
        metrics=MagicMock(),
    )
    with pytest.raises(ZelkovaError):
        client.check_no_new_access(
            existing=_EXISTING_POLICY,
            candidate=_CANDIDATE_POLICY,
            correlation_id=_CORRELATION_ID,
            feature_id="F3",
        )


def _raising_access_analyzer() -> MagicMock:
    client = MagicMock()
    client.check_no_new_access.side_effect = RuntimeError("Access Analyzer unavailable")
    return client
