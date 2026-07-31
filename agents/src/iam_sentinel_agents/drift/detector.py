"""drift/detector -- agents phase-17 §8.

For every Sentinel-owned stack (`stack_name_prefix`, default `"Sentinel"`
per `adapters.settings.sentinel_stack_name_prefix`): `DetectStackDrift`,
poll `DescribeStackDriftDetectionStatus` to completion, then
`DescribeStackResourceDrifts` for the modified/deleted resources. Each
drifted resource is classified against `_NEVER_AUTO_REMEDIATE_LOGICAL_HINTS`
(§8: "Never auto-remediate: KMS key policy changes; Guardrail changes;
Break-glass role changes" -- matched by logical-id/resource-type substring,
since the spec names these by role, not by a literal CloudFormation type)
and `_AUTO_REPAIRABLE_RESOURCE_TYPES` (§8's own example: "IAM policy
manually edited"). Auto-repairable drift calls `UpdateStack` with the
stack's current template (re-asserting the CDK-synthesized desired state);
everything else pages a human via SNS.

Tests inject a stub `CloudFormationClient` rather than relying on moto's
drift APIs: moto does not model `DetectStackDrift`/
`DescribeStackResourceDrifts` (same class of gap ADR 0023 already
documented for Organizations SCP APIs) -- this repo's precedent for that
gap is an injectable boto3-shaped client, not skipping the test.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, UTC
from typing import Any, TYPE_CHECKING

import boto3
from iam_sentinel_adapters.ddb.faults import FaultsClient
from iam_sentinel_adapters.settings import settings
from iam_sentinel_adapters.sns.client import SnsClient

from iam_sentinel_agents.tools.common.retry import record_fault

if TYPE_CHECKING:
    from collections.abc import Callable

    from aws_lambda_powertools.utilities.typing import LambdaContext
    from mypy_boto3_cloudformation.client import CloudFormationClient

# §8 "Never auto-remediate" -- matched against a drifted resource's logical
# id (case-insensitive substring), since the spec names these by role
# (KMS key policy / Guardrail / break-glass role), not by one CFN type.
_NEVER_AUTO_REMEDIATE_LOGICAL_HINTS = ("kms", "guardrail", "breakglass")

# §8's own worked example of "a widely-known auto-repairable pattern."
_AUTO_REPAIRABLE_RESOURCE_TYPES = frozenset({"AWS::IAM::Policy", "AWS::IAM::Role"})

_POLL_BACKOFF_SECONDS = (0.5, 1.0, 2.0, 4.0, 8.0)


@dataclass(frozen=True)
class DriftFinding:
    stack_name: str
    logical_resource_id: str
    resource_type: str
    stack_resource_drift_status: str
    classification: str  # "auto_repaired" | "paged" | "in_sync"


@dataclass(frozen=True)
class DriftReport:
    findings: list[DriftFinding] = field(default_factory=list)


def _is_never_remediate(logical_resource_id: str, resource_type: str) -> bool:
    haystack = f"{logical_resource_id} {resource_type}".lower()
    return any(hint in haystack for hint in _NEVER_AUTO_REMEDIATE_LOGICAL_HINTS)


def _is_auto_repairable(resource_type: str) -> bool:
    return resource_type in _AUTO_REPAIRABLE_RESOURCE_TYPES


def _discover_stack_names(cfn: CloudFormationClient, *, prefix: str) -> list[str]:
    names: list[str] = []
    for page in cfn.get_paginator("list_stacks").paginate(
        StackStatusFilter=["CREATE_COMPLETE", "UPDATE_COMPLETE"]
    ):
        names.extend(
            str(summary["StackName"])
            for summary in page["StackSummaries"]
            if str(summary["StackName"]).startswith(prefix)
        )
    return names


def _wait_for_detection(
    cfn: CloudFormationClient,
    detection_id: str,
    *,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> str:
    """Polls `DescribeStackDriftDetectionStatus` to completion. Returns the
    resolved `StackDriftStatus` (`IN_SYNC` / `DRIFTED` / `NOT_CHECKED`)."""
    for delay in _POLL_BACKOFF_SECONDS:
        response = cfn.describe_stack_drift_detection_status(StackDriftDetectionId=detection_id)
        if response["DetectionStatus"] != "DETECTION_IN_PROGRESS":
            return str(response.get("StackDriftStatus", "NOT_CHECKED"))
        sleep_fn(delay)
    return "NOT_CHECKED"


def detect_and_remediate_drift(
    *,
    stack_names: list[str] | None = None,
    stack_name_prefix: str | None = None,
    cloudformation_client: CloudFormationClient | None = None,
    faults_client: FaultsClient | None = None,
    sns_client: SnsClient | None = None,
    correlation_id: str = "drift-detector-daily",
    sleep_fn: Callable[[float], None] = time.sleep,
) -> DriftReport:
    cfn: CloudFormationClient = cloudformation_client or boto3.client(
        "cloudformation", region_name=settings.region
    )
    faults = faults_client or FaultsClient()
    sns = sns_client or SnsClient(topic_arn=settings.security_topic_arn or None)

    resolved_prefix = stack_name_prefix or settings.sentinel_stack_name_prefix
    resolved_stack_names = stack_names or _discover_stack_names(cfn, prefix=resolved_prefix)

    findings: list[DriftFinding] = []
    for stack_name in resolved_stack_names:
        detection_id = cfn.detect_stack_drift(StackName=stack_name)["StackDriftDetectionId"]
        stack_drift_status = _wait_for_detection(cfn, detection_id, sleep_fn=sleep_fn)
        if stack_drift_status != "DRIFTED":
            continue

        drifts = cfn.describe_stack_resource_drifts(
            StackName=stack_name,
            StackResourceDriftStatusFilters=["MODIFIED", "DELETED"],
        )["StackResourceDrifts"]

        for drift in drifts:
            logical_resource_id = str(drift["LogicalResourceId"])
            resource_type = str(drift["ResourceType"])
            drift_status = str(drift["StackResourceDriftStatus"])

            sns.publish_critical_finding(
                subject="SentinelStackDrift",
                message=(
                    f"stack={stack_name} logical_id={logical_resource_id} "
                    f"type={resource_type} status={drift_status}"
                ),
            )

            if _is_never_remediate(logical_resource_id, resource_type):
                classification = "paged"
            elif _is_auto_repairable(resource_type):
                template = cfn.get_template(StackName=stack_name)["TemplateBody"]
                cfn.update_stack(
                    StackName=stack_name,
                    UsePreviousTemplate=False,
                    TemplateBody=_template_as_string(template),
                    Capabilities=["CAPABILITY_NAMED_IAM"],
                )
                classification = "auto_repaired"
            else:
                classification = "paged"

            record_fault(
                correlation_id=correlation_id,
                fault_class="infra_drift",
                origin=f"drift:detector:{stack_name}",
                action_taken=classification,  # type: ignore[arg-type]
                detail=f"{logical_resource_id} ({resource_type}) drift_status={drift_status}",
                resolved_at=datetime.now(UTC) if classification == "auto_repaired" else None,
                faults_client=faults,
                force_write=True,
            )
            findings.append(
                DriftFinding(
                    stack_name=stack_name,
                    logical_resource_id=logical_resource_id,
                    resource_type=resource_type,
                    stack_resource_drift_status=drift_status,
                    classification=classification,
                )
            )

    return DriftReport(findings=findings)


def _template_as_string(template: Any) -> str:
    if isinstance(template, str):
        return template
    return json.dumps(template)


def drift_detector(_event: dict[str, Any], _context: LambdaContext) -> dict[str, Any]:
    """Daily EventBridge scheduled-rule entrypoint (§8)."""
    report = detect_and_remediate_drift()
    return {
        "findings": [
            {
                "stack_name": f.stack_name,
                "logical_resource_id": f.logical_resource_id,
                "resource_type": f.resource_type,
                "classification": f.classification,
            }
            for f in report.findings
        ]
    }
