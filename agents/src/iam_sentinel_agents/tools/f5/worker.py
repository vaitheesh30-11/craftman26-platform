"""session_kill_worker — attach the emergency Deny policy (phase-06 §4
Step 3), consumed one SQS FIFO message at a time per `MessageGroupId`
(per-account ordering; concurrency is reserved=1 per group at the SQS
event-source-mapping level -- aws-infra concern, not this Lambda's).

On any exception before the DDB write succeeds, no `TerminationRecord` is
persisted (phase-06 §8 Test Plan: "verify DLQ + SNS + no phantom
TerminationRecord in DDB") -- this module publishes a best-effort SNS
failure notice and re-raises so the Lambda-SQS integration's own retry/DLQ
mechanics (aws-infra `foundation_stack.py`: `max_receive_count=3`) take
over.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, UTC
from typing import Any, TYPE_CHECKING

from aws_lambda_powertools import Metrics
from aws_lambda_powertools.metrics import MetricUnit
from iam_sentinel_adapters.ddb.revocations import RevocationsClient
from iam_sentinel_adapters.evidence.client import EvidenceClient
from iam_sentinel_adapters.security_hub.client import SecurityHubClient
from iam_sentinel_adapters.settings import settings as adapter_settings
from iam_sentinel_adapters.sns.client import SnsClient

from iam_sentinel_agents.contracts.session_kill import TerminationRecord
from iam_sentinel_agents.tools.common import cross_account

if TYPE_CHECKING:
    import boto3
    from aws_lambda_powertools.utilities.typing import LambdaContext

    from iam_sentinel_agents.contracts.common import FeatureID

# phase-06 §4 Step 3 / §10 risk mitigation: IAM eventual consistency --
# poll GetRolePolicy on this exact backoff schedule up to 5 attempts.
_VERIFY_BACKOFF_SECONDS = (0.2, 0.5, 1.0, 2.0, 5.0)

_metrics = Metrics(namespace=adapter_settings.metric_namespace, service="iam-sentinel-f5")


class WorkerFailureError(RuntimeError):
    """Raised on any unrecoverable failure attaching the emergency policy."""


def _build_deny_policy(cutoff_iso: str) -> dict[str, Any]:
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Deny",
                "Action": "*",
                "Resource": "*",
                "Condition": {"DateLessThan": {"aws:TokenIssueTime": cutoff_iso}},
            }
        ],
    }


def _poll_until_attached(
    iam: Any, *, role_name: str, policy_name: str, sleep_fn: Any = time.sleep
) -> tuple[int, bool]:
    for attempt, delay in enumerate(_VERIFY_BACKOFF_SECONDS, start=1):
        sleep_fn(delay)
        try:
            iam.get_role_policy(RoleName=role_name, PolicyName=policy_name)
        except iam.exceptions.NoSuchEntityException:
            continue
        else:
            return attempt, True
    return len(_VERIFY_BACKOFF_SECONDS), False


def process_kill_message(
    *,
    account_id: str,
    role_arn: str,
    token_issue_time_cutoff: datetime,
    ttl_expires_at: datetime,
    revocation_policy_name: str,
    correlation_id: str,
    feature_id: FeatureID = "F5",
    session: boto3.Session | None = None,
    revocations_client: RevocationsClient | None = None,
    evidence_client: EvidenceClient | None = None,
    security_hub_client: SecurityHubClient | None = None,
    sns_client: SnsClient | None = None,
    sleep_fn: Any = time.sleep,
) -> TerminationRecord:
    revocations = revocations_client or RevocationsClient()
    role_name = role_arn.split("/")[-1]
    cutoff_iso = token_issue_time_cutoff.astimezone(UTC).isoformat().replace("+00:00", "Z")
    policy_document = _build_deny_policy(cutoff_iso)

    boto_session = session or cross_account.assume(
        account_id, feature_id=feature_id, correlation_id=correlation_id
    )
    iam = boto_session.client("iam")

    try:
        iam.put_role_policy(
            RoleName=role_name,
            PolicyName=revocation_policy_name,
            PolicyDocument=json.dumps(policy_document, separators=(",", ":")),
        )
    except Exception as exc:
        (sns_client or SnsClient()).publish_critical_finding(
            subject="F5 emergency revocation failed",
            message=(
                f"correlation_id={correlation_id} account={account_id} role={role_arn} "
                f"failed to attach {revocation_policy_name}: {exc}"
            ),
        )
        raise WorkerFailureError(str(exc)) from exc

    verify_attempts, verified = _poll_until_attached(
        iam, role_name=role_name, policy_name=revocation_policy_name, sleep_fn=sleep_fn
    )

    now = datetime.now(UTC)
    record = TerminationRecord(
        account_id=account_id,
        role_arn=role_arn,
        revocation_policy_name=revocation_policy_name,
        token_issue_time_cutoff=token_issue_time_cutoff,
        attached_at=now,
        ttl_expires_at=ttl_expires_at,
        verify_attempts=verify_attempts,
        verified_attached=verified,
    )
    revocations.put(
        {**record.model_dump(mode="json"), "correlation_id": correlation_id, "cleaned": False}
    )

    (evidence_client or EvidenceClient()).put_signed_evidence(
        kind="policy_mutation",
        body=record.model_dump(mode="json"),
        correlation_id=correlation_id,
        feature_id=feature_id,
    )
    (security_hub_client or SecurityHubClient()).import_findings(
        [_asff_finding(record, correlation_id)]
    )

    _metrics.add_dimension(name="account", value=account_id)
    _metrics.add_metric(name="SentinelEmergencyRevocations", unit=MetricUnit.Count, value=1)

    if not verified:
        (sns_client or SnsClient()).publish_critical_finding(
            subject="F5 emergency revocation unverified",
            message=(
                f"correlation_id={correlation_id} account={account_id} role={role_arn} "
                f"policy {revocation_policy_name} attached but not observed within "
                f"{verify_attempts} polls"
            ),
        )

    return record


def session_kill_worker(event: dict[str, Any], _context: LambdaContext) -> dict[str, Any]:
    """SQS FIFO event-source-mapping entrypoint (not a Bedrock action group
    -- `sentinel_handler` wraps Bedrock envelopes only, so this Lambda
    parses the native SQS batch shape directly). Returns
    `batchItemFailures` (partial-batch-failure reporting) so only the
    records that actually failed are retried/DLQ'd, not the whole batch.
    """
    failures: list[dict[str, str]] = []
    for record in event.get("Records", []):
        message_id = record["messageId"]
        try:
            body = json.loads(record["body"])
            process_kill_message(
                account_id=body["account_id"],
                role_arn=body["role_arn"],
                token_issue_time_cutoff=datetime.fromisoformat(body["token_issue_time_cutoff"]),
                ttl_expires_at=datetime.fromisoformat(body["ttl_expires_at"]),
                revocation_policy_name=body["revocation_policy_name"],
                correlation_id=body["correlation_id"],
            )
        except Exception:  # noqa: BLE001 -- one bad message must not sink the batch
            failures.append({"itemIdentifier": message_id})
    return {"batchItemFailures": failures}


def _asff_finding(record: TerminationRecord, correlation_id: str) -> dict[str, Any]:
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "SchemaVersion": "2018-10-08",
        "Id": f"iam-sentinel/f5/{correlation_id}/{record.account_id}/{record.role_arn}",
        "ProductArn": (
            f"arn:aws:securityhub:{adapter_settings.region}:"
            f"{record.account_id}:product/{record.account_id}/default"
        ),
        "GeneratorId": "iam-sentinel-f5-session-terminator",
        "AwsAccountId": record.account_id,
        "Types": ["Sensitive Data Identifications/Credential Compromise"],
        "CreatedAt": now,
        "UpdatedAt": now,
        "Severity": {"Label": "CRITICAL"},
        "Title": "IAM Sentinel emergency SSO session revocation",
        "Description": (
            f"Attached {record.revocation_policy_name} to {record.role_arn} denying "
            f"sessions issued before {record.token_issue_time_cutoff.isoformat()}."
        ),
        "Resources": [
            {"Type": "AwsIamRole", "Id": record.role_arn, "Region": adapter_settings.region}
        ],
        "ProductFields": {"Product": "IAM Sentinel"},
    }
