"""shadow_guard_ingest -- phase-07 §4 Step 1-2.

Not agent-callable (phase-07 §3: "Ingest Lambda is not agent-callable — it
is CloudWatch-Logs-driven"), so this module does NOT use
`tools/common/runtime.sentinel_handler` -- that decorator parses Bedrock
action-group envelopes, and a CloudWatch Logs subscription-filter event is
a completely different shape (gzip+base64 `awslogs.data`). `handler` below
is this Lambda's own plain entrypoint.

Unlike every specialist tool (whose `Finding`s are persisted once, by
Prime's post-turn processing after a completed agent turn -- see
`prime/post_turn.py`), no agent turn ever runs here: CloudWatch invokes this
Lambda directly. It is therefore F6's own responsibility -- and the first
real caller anywhere in `agents/` -- to call
`iam_sentinel_adapters.ddb.findings.FindingsClient.put` and
`iam_sentinel_adapters.evidence.client.EvidenceClient.put_signed_evidence`
itself, per phase-07 §4 Step 2 ("Persist to DDB SentinelFindings with TTL
90 days") and §7's IAM policy (`kms:Sign`, `s3:PutObject` on
`SentinelEvidence/f6/*`).
"""

from __future__ import annotations

import base64
import gzip
import json
from datetime import datetime, timedelta, UTC
from typing import Any, cast, Literal, TYPE_CHECKING

from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.metrics import MetricUnit
from iam_sentinel_adapters.ddb.findings import FindingsClient
from iam_sentinel_adapters.ddb.policies import PoliciesCacheClient
from iam_sentinel_adapters.evidence.client import EvidenceClient

from iam_sentinel_agents.contracts.finding import AwsDocCitation, Finding
from iam_sentinel_agents.contracts.shadow_guard import ShadowViolation
from iam_sentinel_agents.ids import new_ulid
from iam_sentinel_agents.settings import settings
from iam_sentinel_agents.tools.common import shadow_guard_service_map
from iam_sentinel_agents.tools.common.shadow_guard_scp_evaluator import (
    evaluate_action,
    EvaluationResult,
)
from iam_sentinel_agents.tools.f6.severity import classify_severity

if TYPE_CHECKING:
    from aws_lambda_powertools.utilities.typing import LambdaContext

    from iam_sentinel_agents.tools.common.shadow_guard_scp_evaluator import LevelPolicies

logger = Logger(service="iam-sentinel-f6-ingest", level=settings.log_level)
tracer = Tracer(service="iam-sentinel-f6-ingest")
metrics = Metrics(namespace=settings.metric_namespace, service="iam-sentinel-f6-ingest")

_READ_PREFIXES = ("list", "get", "describe", "view")
_FINDINGS_TTL_DAYS = 90

# Both AWS quotes phase-07 §5's prompt requires citing on every Finding.
# `Finding.aws_doc_citation` (docs/DATA_CONTRACTS.md §4) carries exactly
# one `AwsDocCitation` -- there is no list field for a second quote. The
# primary quote (Organizations' own documentation, the more specific of the
# two) is the structured citation; the second (AWS prescriptive guidance)
# is embedded verbatim in `detail` so "cite both" is honored in the
# Finding's actual text even though the schema cannot carry two structured
# citations. See docs/decisions/0023.
_PRIMARY_QUOTE = "SCPs have no effect on users or roles in the management account."
_SECONDARY_QUOTE = (
    "SCPs don't apply to the management account — your production workloads "
    "have no SCP guardrails."
)
_PRIMARY_SOURCE = "AWS Organizations User Guide"
_SECONDARY_SOURCE = "AWS prescriptive guidance"
_CITATION_URL = (
    "https://docs.aws.amazon.com/organizations/latest/userguide/orgs_manage_policies_scps.html"
)
_RETRIEVED_ON = "2026-07-31"


def decode_cloudwatch_logs_event(event: dict[str, Any]) -> list[dict[str, Any]]:
    """Decode a CloudWatch Logs subscription-filter Lambda event into its
    `logEvents` list. Returns `[]` for an event with no `awslogs.data`
    (defensive -- a malformed trigger should never crash cold ingestion).
    """
    raw = event.get("awslogs", {}).get("data")
    if raw is None:
        return []
    decompressed = gzip.decompress(base64.b64decode(raw))
    payload = json.loads(decompressed)
    return list(payload.get("logEvents", []))


def parse_cloudtrail_record(log_event: dict[str, Any]) -> dict[str, Any] | None:
    message = log_event.get("message")
    if not isinstance(message, str):
        return None
    try:
        return dict(json.loads(message))
    except json.JSONDecodeError:
        return None


def _is_read_event(event_name: str) -> bool:
    lowered = event_name.lower()
    return lowered.startswith(_READ_PREFIXES) or lowered.startswith("batchget")


def build_action(event_source: str, event_name: str) -> str:
    prefix = shadow_guard_service_map.prefix_for(event_source)
    return f"{prefix}:{event_name}".lower()


def _principal_type(
    user_identity: dict[str, Any],
) -> Literal["Root", "IAMUser", "AssumedRole", "FederatedUser"]:
    raw_type = str(user_identity.get("type", ""))
    if raw_type == "Root":
        return "Root"
    if raw_type == "IAMUser":
        return "IAMUser"
    if raw_type == "FederatedUser":
        return "FederatedUser"
    return "AssumedRole"


def _parse_event_time(raw: str | None) -> datetime:
    if raw is None:
        return datetime.now(UTC)
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def evaluate_cloudtrail_event(
    cloudtrail_event: dict[str, Any], chain: list[LevelPolicies]
) -> ShadowViolation | None:
    """Pure per-event evaluation (phase-07 §4 Step 2) -- no AWS calls, so
    this is the function the unit test suite exercises directly against
    crafted CloudTrail records rather than a full moto-mocked Lambda
    invocation.
    """
    event_name = str(cloudtrail_event.get("eventName", ""))
    if not event_name or _is_read_event(event_name):
        return None

    action = build_action(str(cloudtrail_event.get("eventSource", "")), event_name)
    result: EvaluationResult = evaluate_action(chain=chain, action=action)
    if result.allowed:
        return None

    user_identity = cloudtrail_event.get("userIdentity", {})
    if not isinstance(user_identity, dict):
        user_identity = {}
    principal_arn = user_identity.get("arn") or "arn:aws:iam::000000000000:root"
    denied_level: Literal["root", "ou"] = "ou" if result.denying_level == "ou" else "root"
    severity = classify_severity(action, denied_level)

    return ShadowViolation(
        action=action,
        principal_arn=principal_arn,
        principal_type=_principal_type(user_identity),
        would_be_denied_by_scp_arn=result.denying_policy_arn
        or "arn:aws:organizations::000000000000:policy/o-unknown/service_control_policy/p-unknown",
        denying_statement_id=result.denying_statement_id,
        would_be_denied_at_level=denied_level,
        event_id=str(cloudtrail_event.get("eventID", "unknown")),
        event_time=_parse_event_time(cloudtrail_event.get("eventTime")),
        severity=severity,
    )


def violation_to_finding(violation: ShadowViolation, *, account_id: str) -> Finding:
    detail = (
        f"{violation.principal_arn} invoked {violation.action} in the management "
        f"account; the same call would be DENIED in a member account by "
        f"{violation.would_be_denied_by_scp_arn} at the {violation.would_be_denied_at_level} "
        f'level. Second AWS citation ({_SECONDARY_SOURCE}): "{_SECONDARY_QUOTE}"'
    )
    now = datetime.now(UTC)
    return Finding(
        finding_id=new_ulid(),
        feature_id="F6",
        account_id=account_id,
        principal_arn=violation.principal_arn,
        resource_arn=None,
        severity=violation.severity,
        title=f"Shadow SCP violation: {violation.action}",
        detail=detail[:8192],
        aws_doc_citation=AwsDocCitation(
            gap_id="F6",
            quote=_PRIMARY_QUOTE,
            source=_PRIMARY_SOURCE,
            url=_CITATION_URL,
            retrieved_on=_RETRIEVED_ON,
        ),
        payload=violation.model_dump(mode="json"),
        detected_at=now,
        expires_at=now + timedelta(days=_FINDINGS_TTL_DAYS),
    )


def handler(
    event: dict[str, Any],
    _context: LambdaContext,
    *,
    policies: PoliciesCacheClient | None = None,
    findings: FindingsClient | None = None,
    evidence: EvidenceClient | None = None,
) -> dict[str, Any]:
    """`policies`/`findings`/`evidence` are injection points for tests
    (mirroring `PrimePostTurnProcessor`'s constructor injection and F1's
    `session`/`iam_client` parameters) -- production always uses the
    default adapters-side clients.
    """
    log_events = decode_cloudwatch_logs_event(event)
    policies = policies or PoliciesCacheClient()
    findings = findings or FindingsClient()
    evidence = evidence or EvidenceClient()

    org_id = settings.mgmt_org_id
    # `PoliciesCacheClient.get_chain` is adapters-side and returns plain dicts
    # (module boundary: adapters never imports agents' `LevelPolicies`
    # TypedDict) -- the shape is structurally identical, so a `cast` here
    # is honest rather than a type-safety workaround.
    chain = cast("list[LevelPolicies]", policies.get_chain(org_id))

    violations: list[ShadowViolation] = []
    for log_event in log_events:
        cloudtrail_event = parse_cloudtrail_record(log_event)
        if cloudtrail_event is None:
            continue
        violation = evaluate_cloudtrail_event(cloudtrail_event, chain)
        if violation is None:
            continue
        violations.append(violation)
        account_id = str(cloudtrail_event.get("recipientAccountId", settings.mgmt_account_id))
        finding = violation_to_finding(violation, account_id=account_id)
        findings.put(finding.model_dump(mode="json"))
        evidence.put_signed_evidence(
            kind="specialist_output",
            body=finding.model_dump(mode="json"),
            correlation_id=violation.event_id,
            feature_id="F6",
        )

    metrics.add_metric(name="ShadowViolationsFound", unit=MetricUnit.Count, value=len(violations))
    metrics.add_metric(
        name="CloudTrailEventsIngested", unit=MetricUnit.Count, value=len(log_events)
    )
    logger.info(
        "shadow_guard_ingest_batch_complete",
        events_ingested=len(log_events),
        violations_found=len(violations),
    )
    return {"events_ingested": len(log_events), "violations_found": len(violations)}
