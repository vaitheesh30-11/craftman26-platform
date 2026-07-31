"""E-08 — Proposed SCP breaks Auto Scaling SLR (phase-13 scenario table).
Real `tools/f8/scan.evaluate_scp` (pure computation) against the
AutoScaling SLR row, wired through the real `PrimePostTurnProcessor` so
the conflict's exemption survives a full compose -> sign -> persist
round trip, not just the unit-level assertion `tests/unit/f8/test_scan.py`
already covers. Passes when: conflict emitted, `safe_scp` includes an
`ArnNotLike` exemption for the AutoScaling SLR.
"""

from __future__ import annotations

from datetime import datetime, UTC
from typing import TYPE_CHECKING

from iam_sentinel_agents.contracts.finding import Finding
from iam_sentinel_agents.contracts.verdict import SpecialistVerdict, ToolInvocation
from iam_sentinel_agents.tools.f8.scan import evaluate_scp
from tests.contract._factories import make_citation, make_query

if TYPE_CHECKING:
    from tests.e2e.conftest import PostTurnHarness

_AUTOSCALING_ROW = {
    "service_principal": "autoscaling.amazonaws.com",
    "slr_name": "AWSServiceRoleForAutoScaling",
    "required_actions": ["ec2:TerminateInstances", "ec2:RunInstances", "ec2:DescribeInstances"],
    "optional_actions": [],
    "core_actions": ["ec2:TerminateInstances"],
    "db_version": "7",
}
_PROPOSED_SCP = {
    "Version": "2012-10-17",
    "Statement": [{"Effect": "Deny", "Action": "ec2:TerminateInstances", "Resource": "*"}],
}
_CORRELATION_ID = "01JBP2VHF9K3Q0Z8R7X6M5N4A8"


def test_e08_scp_break_of_autoscaling_slr_emits_arnnotlike_exemption(
    post_turn_harness: PostTurnHarness,
) -> None:
    result = evaluate_scp(_PROPOSED_SCP, [_AUTOSCALING_ROW])

    assert len(result["conflicts"]) == 1
    conflict = result["conflicts"][0]
    assert conflict["service_principal"] == "autoscaling.amazonaws.com"
    assert conflict["impact"] == "CRITICAL"

    safe_statement = result["safe_scp"]["Statement"][0]
    assert safe_statement["Condition"]["ArnNotLike"]["aws:PrincipalArn"] == (
        "arn:aws:iam::*:role/aws-service-role/autoscaling.amazonaws.com/*"
    )
    assert all(stmt.get("Effect") != "Allow" for stmt in result["safe_scp"]["Statement"])

    slr_role_arn = (
        "arn:aws:iam::123456789012:role/aws-service-role/"
        "autoscaling.amazonaws.com/AWSServiceRoleForAutoScaling"
    )
    finding = Finding(
        finding_id="01JBP2VHF9K3Q0Z8R7X6M5N4A9",
        feature_id="F8",
        account_id="123456789012",
        principal_arn=slr_role_arn,
        severity="CRITICAL",
        title="Proposed SCP breaks the AutoScaling SLR",
        detail="Denying ec2:TerminateInstances also blocks AWSServiceRoleForAutoScaling's core action.",
        aws_doc_citation=make_citation(),
        payload=result,
        detected_at=datetime.now(UTC),
    )
    verdict = SpecialistVerdict(
        correlation_id=_CORRELATION_ID,
        feature_id="F8",
        verdict="CONFIRM",
        reason="1 CRITICAL SLR conflict; safe_scp carries an ArnNotLike exemption",
        findings=[finding],
        tool_invocations=[
            ToolInvocation(tool_name="slr_scan", input_hash="c" * 64, output_hash="d" * 64, duration_ms=10)
        ],
        duration_ms=10,
    )
    query = make_query().model_copy(update={"correlation_id": _CORRELATION_ID})

    decision = post_turn_harness.processor.process(
        query=query, verdicts=[verdict], narrative="AutoScaling SLR would break under the proposed SCP."
    )

    assert decision is not None
    assert decision.status == "ANSWERED"
    persisted_payload = decision.findings[0].payload
    persisted_condition = persisted_payload["safe_scp"]["Statement"][0]["Condition"]
    assert persisted_condition["ArnNotLike"]["aws:PrincipalArn"] == (
        "arn:aws:iam::*:role/aws-service-role/autoscaling.amazonaws.com/*"
    )
