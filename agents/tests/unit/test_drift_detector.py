"""`drift.detector` (agents phase-17 §8). §12 Test Plan: "moto fixture
where a stack has an out-of-band change; verify detection and (for
auto-repairable class) update." Moto does not model
`DetectStackDrift`/`DescribeStackResourceDrifts` (same class of gap ADR
0023 already documented for Organizations SCP APIs), so this exercises the
classification/remediation logic against a stubbed `CloudFormationClient`
instead of skipping the scenario -- the repo's established precedent for
an AWS API surface no test double can fabricate.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from iam_sentinel_agents.drift.detector import detect_and_remediate_drift, drift_detector

pytestmark = pytest.mark.unit


def _cfn_client(*, drift_status: str, drifts: list[dict[str, object]]) -> MagicMock:
    cfn = MagicMock()
    cfn.detect_stack_drift.return_value = {"StackDriftDetectionId": "detect-1"}
    cfn.describe_stack_drift_detection_status.return_value = {
        "DetectionStatus": "DETECTION_COMPLETE",
        "StackDriftStatus": drift_status,
    }
    cfn.describe_stack_resource_drifts.return_value = {"StackResourceDrifts": drifts}
    cfn.get_template.return_value = {"TemplateBody": {"Resources": {}}}
    return cfn


def test_in_sync_stack_produces_no_findings() -> None:
    cfn = _cfn_client(drift_status="IN_SYNC", drifts=[])
    faults_client = MagicMock()

    report = detect_and_remediate_drift(
        stack_names=["SentinelFoundationStack"],
        cloudformation_client=cfn,
        faults_client=faults_client,
        sns_client=MagicMock(),
        sleep_fn=lambda _delay: None,
    )

    assert report.findings == []
    cfn.describe_stack_resource_drifts.assert_not_called()
    faults_client.put.assert_not_called()


def test_iam_policy_drift_is_auto_repaired() -> None:
    cfn = _cfn_client(
        drift_status="DRIFTED",
        drifts=[
            {
                "LogicalResourceId": "AuditorReadOnlyPolicy",
                "ResourceType": "AWS::IAM::Policy",
                "StackResourceDriftStatus": "MODIFIED",
            }
        ],
    )
    faults_client = MagicMock()
    sns_client = MagicMock()

    report = detect_and_remediate_drift(
        stack_names=["SentinelFoundationStack"],
        cloudformation_client=cfn,
        faults_client=faults_client,
        sns_client=sns_client,
        sleep_fn=lambda _delay: None,
    )

    assert len(report.findings) == 1
    assert report.findings[0].classification == "auto_repaired"
    cfn.update_stack.assert_called_once()
    sns_client.publish_critical_finding.assert_called_once()
    faults_client.put.assert_called_once()
    written = faults_client.put.call_args.args[0]
    assert written["action_taken"] == "auto_repaired"
    assert written["fault_class"] == "infra_drift"
    assert written["resolved_at"] is not None


@pytest.mark.parametrize(
    ("logical_id", "resource_type"),
    [
        ("EvidenceKmsKey", "AWS::KMS::Key"),
        ("PrimeGuardrail", "AWS::Bedrock::Guardrail"),
        ("BreakGlassRole", "AWS::IAM::Role"),
    ],
)
def test_never_auto_remediate_resources_are_paged_not_updated(
    logical_id: str, resource_type: str
) -> None:
    cfn = _cfn_client(
        drift_status="DRIFTED",
        drifts=[
            {
                "LogicalResourceId": logical_id,
                "ResourceType": resource_type,
                "StackResourceDriftStatus": "MODIFIED",
            }
        ],
    )
    faults_client = MagicMock()

    report = detect_and_remediate_drift(
        stack_names=["SentinelSecurityStack"],
        cloudformation_client=cfn,
        faults_client=faults_client,
        sns_client=MagicMock(),
        sleep_fn=lambda _delay: None,
    )

    assert report.findings[0].classification == "paged"
    cfn.update_stack.assert_not_called()
    assert faults_client.put.call_args.args[0]["action_taken"] == "paged"
    assert faults_client.put.call_args.args[0]["resolved_at"] is None


def test_unrecognized_resource_type_is_paged_by_default() -> None:
    cfn = _cfn_client(
        drift_status="DRIFTED",
        drifts=[
            {
                "LogicalResourceId": "SomeQueue",
                "ResourceType": "AWS::SQS::Queue",
                "StackResourceDriftStatus": "DELETED",
            }
        ],
    )

    report = detect_and_remediate_drift(
        stack_names=["SentinelFoundationStack"],
        cloudformation_client=cfn,
        faults_client=MagicMock(),
        sns_client=MagicMock(),
        sleep_fn=lambda _delay: None,
    )

    assert report.findings[0].classification == "paged"


def test_stack_discovery_filters_by_prefix_when_no_names_given() -> None:
    cfn = _cfn_client(drift_status="IN_SYNC", drifts=[])
    cfn.get_paginator.return_value.paginate.return_value = [
        {
            "StackSummaries": [
                {"StackName": "SentinelFoundationStack"},
                {"StackName": "SomeOtherStack"},
            ]
        }
    ]

    detect_and_remediate_drift(
        cloudformation_client=cfn,
        stack_name_prefix="Sentinel",
        faults_client=MagicMock(),
        sns_client=MagicMock(),
        sleep_fn=lambda _delay: None,
    )

    cfn.detect_stack_drift.assert_called_once_with(StackName="SentinelFoundationStack")


def test_drift_detector_lambda_entrypoint_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    from iam_sentinel_agents.drift import detector as detector_module
    from iam_sentinel_agents.drift.detector import DriftFinding, DriftReport

    monkeypatch.setattr(
        detector_module,
        "detect_and_remediate_drift",
        lambda: DriftReport(
            findings=[
                DriftFinding(
                    stack_name="SentinelFoundationStack",
                    logical_resource_id="X",
                    resource_type="AWS::IAM::Policy",
                    stack_resource_drift_status="MODIFIED",
                    classification="auto_repaired",
                )
            ]
        ),
    )

    output = drift_detector({}, None)

    assert output["findings"][0]["classification"] == "auto_repaired"
