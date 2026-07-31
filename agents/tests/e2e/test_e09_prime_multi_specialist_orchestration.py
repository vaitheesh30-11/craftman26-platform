"""E-09 — Prime multi-specialist orchestration, F1+F4 (phase-13 scenario
table). Real `prime/decision_composer.compose_status` +
`PrimePostTurnProcessor.process` given two specialist verdicts as if
Prime's Bedrock-side SUPERVISOR fan-out (docs/decisions/0013 Gap 2 -- not
agents/'s code to write, no Python routing function exists) had already
invoked F1 and F4 in parallel and returned both verdicts. Passes when:
two specialists invoked (both present in the persisted DecisionRecord),
synthesized into one `DecisionRecord`.
"""

from __future__ import annotations

from datetime import datetime, UTC
from typing import TYPE_CHECKING

from iam_sentinel_agents.contracts.finding import Finding
from iam_sentinel_agents.contracts.verdict import SpecialistVerdict, ToolInvocation
from tests.contract._factories import make_citation, make_query

if TYPE_CHECKING:
    from tests.e2e.conftest import PostTurnHarness

_CORRELATION_ID = "01JBP2VHF9K3Q0Z8R7X6M5N4B1"


def _f1_verdict() -> SpecialistVerdict:
    finding = Finding(
        finding_id="01JBP2VHF9K3Q0Z8R7X6M5N4B2",
        feature_id="F1",
        account_id="123456789012",
        principal_arn="arn:aws:iam::123456789012:user/Deployer",
        severity="CRITICAL",
        title="PassRole admin shortcut",
        detail="Deployer reaches AdministratorAccess in 1 hop via PassRole.",
        aws_doc_citation=make_citation(),
        detected_at=datetime.now(UTC),
    )
    return SpecialistVerdict(
        correlation_id=_CORRELATION_ID,
        feature_id="F1",
        verdict="CONFIRM",
        reason="1 CRITICAL PassRole finding",
        findings=[finding],
        tool_invocations=[
            ToolInvocation(tool_name="passrole_scan", input_hash="e" * 64, output_hash="f" * 64, duration_ms=30)
        ],
        duration_ms=30,
    )


def _f4_verdict() -> SpecialistVerdict:
    return SpecialistVerdict(
        correlation_id=_CORRELATION_ID,
        feature_id="F4",
        verdict="CONFIRM",
        reason="Proposed SCP would not break any observed CI/CD role in the last 90 days",
        findings=[],
        tool_invocations=[
            ToolInvocation(tool_name="scp_impact_simulate", input_hash="1" * 64, output_hash="2" * 64, duration_ms=15)
        ],
        duration_ms=15,
    )


def test_e09_two_specialists_synthesize_into_one_decision_record(
    post_turn_harness: PostTurnHarness,
) -> None:
    verdicts = [_f1_verdict(), _f4_verdict()]
    query = make_query().model_copy(update={"correlation_id": _CORRELATION_ID})

    decision = post_turn_harness.processor.process(
        query=query,
        verdicts=verdicts,
        narrative="F1 found a CRITICAL PassRole exposure; F4 confirms the proposed SCP is safe.",
    )

    assert decision is not None
    assert {v.feature_id for v in decision.specialist_verdicts} == {"F1", "F4"}
    assert len(decision.specialist_verdicts) == 2
    # any CRITICAL finding -> status stays ANSWERED with the finding surfaced,
    # per `decision_composer.compose_status`'s documented precedence.
    assert decision.status == "ANSWERED"
    assert len(decision.findings) == 1
    # SNS is the real, moto-backed `SnsClient` here (not a mock) -- reaching
    # this line without an exception is the proof `_escalate_critical`'s
    # `publish_critical_finding` call succeeded against moto's SNS.
    post_turn_harness.security_hub.import_findings.assert_called_once()
