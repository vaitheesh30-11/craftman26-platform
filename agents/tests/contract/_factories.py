"""Deterministic factories for valid contract instances.

Kept in a shared module so every test file can build a valid instance in one
line, and property tests can perturb from a known-good baseline.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from iam_sentinel_agents.contracts import (
    AwsDocCitation,
    DecisionRecord,
    EvidenceRef,
    Finding,
    RemediationPlan,
    SentinelQuery,
    SpecialistTask,
    SpecialistVerdict,
    ToolInvocation,
    UntrustedContextBlock,
    ZelkovaCheck,
)

VALID_ULID = "01JBP2VHF9K3Q0Z8R7X6M5N4A3"
VALID_ULID_2 = "01JBP2VHF9K3Q0Z8R7X6M5N4A4"
VALID_ACCOUNT = "111122223333"
VALID_ROLE_ARN = "arn:aws:iam::111122223333:role/DevOpsEngineer"
VALID_PRINCIPAL_ARN = "arn:aws:iam::111122223333:role/Auditor"
VALID_KMS_ARN = "arn:aws:kms:us-east-1:111122223333:key/mrk-a1b2c3d4e5f6789012345678901234ab"
SHA256_ONES = "1" * 64
SHA256_TWOS = "2" * 64
SHA256_THREES = "3" * 64
NOW = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)

CANONICAL_QUOTE = (
    "PassRole is not an API call. No CloudTrail logs are generated for iam:PassRole. "
    "The iam:PassRole action is not tracked and is not included in IAM action last "
    "accessed information. It is not included in generated policies."
)


def make_evidence_ref() -> EvidenceRef:
    return EvidenceRef(
        bucket="sentinel-evidence-dev",
        key=f"f1/2026/07/30/{VALID_ULID}/specialist_output/{SHA256_ONES}.json",
        version_id="version-abc",
        kms_key_arn=VALID_KMS_ARN,
        signature="base64signature==",
        sha256=SHA256_ONES,
        stored_at=NOW,
    )


def make_citation() -> AwsDocCitation:
    return AwsDocCitation(
        gap_id="F1",
        quote=CANONICAL_QUOTE,
        source="AWS IAM User Guide",
        url="https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_use_passrole.html",
        retrieved_on="2026-07-30",
    )


def make_finding(**overrides: Any) -> Finding:
    defaults: dict[str, Any] = {
        "finding_id": VALID_ULID,
        "feature_id": "F1",
        "account_id": VALID_ACCOUNT,
        "principal_arn": VALID_PRINCIPAL_ARN,
        "severity": "CRITICAL",
        "title": "PassRole to AdministratorAccess reachable in 1 hop",
        "detail": "Principal can pass role arn:aws:iam::111122223333:role/AdminRole to lambda.",
        "aws_doc_citation": make_citation(),
        "payload": {},
        "detected_at": NOW,
    }
    defaults.update(overrides)
    return Finding(**defaults)


def make_zelkova_pass() -> ZelkovaCheck:
    return ZelkovaCheck(
        **{"pass": True},
        witness=None,
        latency_ms=42,
        invoked_at=NOW,
        baseline_hash=SHA256_ONES,
        candidate_hash=SHA256_TWOS,
    )


def make_remediation_dry() -> RemediationPlan:
    return RemediationPlan(
        action="attach_inline_policy",
        target_arn=VALID_ROLE_ARN,
        policy_document={"Version": "2012-10-17", "Statement": []},
        ttl_seconds=3600,
        dry_run=True,
    )


def make_tool_invocation(*, with_zelkova: bool = False) -> ToolInvocation:
    return ToolInvocation(
        tool_name="passrole_scan",
        input_hash=SHA256_ONES,
        output_hash=SHA256_TWOS,
        duration_ms=500,
        zelkova_check=make_zelkova_pass() if with_zelkova else None,
    )


def make_verdict(**overrides: Any) -> SpecialistVerdict:
    defaults: dict[str, Any] = {
        "correlation_id": VALID_ULID,
        "feature_id": "F1",
        "verdict": "CONFIRM",
        "reason": "1 CRITICAL finding: admin shortcut via PassRole",
        "findings": [make_finding()],
        "remediation": None,
        "tool_invocations": [make_tool_invocation()],
        "duration_ms": 1234,
    }
    defaults.update(overrides)
    return SpecialistVerdict(**defaults)


def make_query() -> SentinelQuery:
    return SentinelQuery(
        correlation_id=VALID_ULID,
        principal=VALID_PRINCIPAL_ARN,
        query_text="audit passrole for account 111122223333",
        hints={"account_id": VALID_ACCOUNT},
        include_arns_in_output=False,
        submitted_at=NOW,
    )


def make_task() -> SpecialistTask:
    return SpecialistTask(
        correlation_id=VALID_ULID,
        feature_id="F1",
        tool_hint="passrole_scan",
        trusted_input={"account_id": VALID_ACCOUNT},
        untrusted_context=[
            UntrustedContextBlock(type="role_names", body="role/DevOpsEngineer\nrole/PipelineDeployer")
        ],
        retry_count=0,
    )


def make_decision() -> DecisionRecord:
    return DecisionRecord(
        decision_id=VALID_ULID_2,
        correlation_id=VALID_ULID,
        principal=VALID_PRINCIPAL_ARN,
        query=make_query(),
        specialist_verdicts=[make_verdict()],
        findings=[make_finding()],
        remediations_proposed=[make_remediation_dry()],
        remediations_applied=[],
        status="ANSWERED",
        narrative="Found 1 CRITICAL PassRole finding. Principal can reach AdministratorAccess in 1 hop.",
        evidence_ref=make_evidence_ref(),
        decided_at=NOW,
    )
