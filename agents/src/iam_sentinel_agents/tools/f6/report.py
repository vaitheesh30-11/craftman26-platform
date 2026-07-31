"""shadow_guard_report -- phase-07 §4 Step 4-5, and the one agent-callable
tool F6 exposes (`action_groups/f6_shadow_guard.yaml`).

`build_shadow_violation_payload`/`compensating_controls_for` are pure
(operate on already-fetched `ShadowViolation`s) so tests exercise the
aggregation and CDK-generation logic without moto -- the DDB read and S3
report write are `shadow_guard_report`'s own concern, mirroring F1's
scan/graph split (`tools/f1/scan.py` fetches, `tools/f1/graph.py`
computes).
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, UTC
from typing import Any, cast, TYPE_CHECKING

import boto3
from iam_sentinel_adapters.ddb.findings import FindingsClient
from iam_sentinel_adapters.settings import settings as adapters_settings

from iam_sentinel_agents.contracts.common import Severity, SEVERITY_ORDER
from iam_sentinel_agents.contracts.shadow_guard import (
    CompensatingControl,
    ShadowViolation,
    ShadowViolationPayload,
)
from iam_sentinel_agents.tools.common.runtime import sentinel_handler
from iam_sentinel_agents.tools.f6.cdk_templates import compensating_control_for_action

if TYPE_CHECKING:
    from aws_lambda_powertools.utilities.typing import LambdaContext
    from mypy_boto3_s3 import S3Client

    from iam_sentinel_agents.tools.common.event_parser import ParsedInvocation

_TOP_ACTIONS_LIMIT = 10


def _week_id(when: datetime) -> str:
    iso_year, iso_week, _ = when.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def build_shadow_violation_payload(
    violations: list[ShadowViolation],
    *,
    days_back: int,
    total_events_ingested: int,
    weekly_trend: dict[str, int] | None = None,
) -> ShadowViolationPayload:
    counts_by_action: Counter[str] = Counter(v.action for v in violations)
    denying_by_action: dict[str, set[str]] = defaultdict(set)
    for violation in violations:
        denying_by_action[violation.action].add(violation.would_be_denied_by_scp_arn)

    top_actions: list[dict[str, object]] = [
        {"action": action, "count": count, "denying_scps": sorted(denying_by_action[action])}
        for action, count in counts_by_action.most_common(_TOP_ACTIONS_LIMIT)
    ]

    return ShadowViolationPayload(
        days_back=days_back,
        total_events_ingested=total_events_ingested,
        violation_count=len(violations),
        violations=violations,
        top_actions=top_actions,
        weekly_trend=weekly_trend,
    )


def filter_by_severity(
    violations: list[ShadowViolation], severity_filter: Severity
) -> list[ShadowViolation]:
    threshold = SEVERITY_ORDER[severity_filter]
    return [v for v in violations if SEVERITY_ORDER[v.severity] >= threshold]


def compute_weekly_trend(violations: list[ShadowViolation]) -> dict[str, int]:
    trend: Counter[str] = Counter(_week_id(v.event_time) for v in violations)
    return dict(sorted(trend.items()))


def compensating_controls_for(payload: ShadowViolationPayload) -> list[CompensatingControl]:
    """One `EventBridgeRule` control per top action (phase-07 §4 Step 5's
    "immediate SNS alert" template) plus a `ConfigRule` for the single
    highest-volume action (§4 Step 5's "slow-loop drift" template) -- the
    spec names both templates but doesn't say how many of each to emit per
    report; one alert per distinct offending action plus one drift-
    detection rule for the worst offender is the minimal set that actually
    covers §4 Step 5's two named template kinds without generating a
    ConfigRule per action (Config rules are billed per-rule-per-account
    and this report can list up to `_TOP_ACTIONS_LIMIT` actions).
    """
    controls = [
        compensating_control_for_action(
            str(entry["action"]), call_count=cast("int", entry["count"])
        )
        for entry in payload.top_actions
    ]
    if payload.top_actions:
        worst = payload.top_actions[0]
        controls.append(
            compensating_control_for_action(
                str(worst["action"]),
                call_count=cast("int", worst["count"]),
                control_kind="ConfigRule",
            )
        )
    return controls


def build_report(
    violations: list[ShadowViolation],
    *,
    days_back: int,
    severity_filter: Severity,
    total_events_ingested: int,
) -> tuple[ShadowViolationPayload, list[CompensatingControl]]:
    filtered = filter_by_severity(violations, severity_filter)
    payload = build_shadow_violation_payload(
        filtered,
        days_back=days_back,
        total_events_ingested=total_events_ingested,
        weekly_trend=compute_weekly_trend(filtered),
    )
    controls = compensating_controls_for(payload)
    return payload, controls


def load_recent_violations(
    *, days_back: int, findings: FindingsClient | None = None
) -> tuple[list[ShadowViolation], int]:
    """Fetch F6 findings from the last `days_back` days and unwrap their
    `payload` back into `ShadowViolation`s. Returns `(violations,
    total_events_ingested)` -- `total_events_ingested` is approximated as
    the finding count read (the true per-batch ingestion count is only
    ever logged, not persisted per-event, per `tools/f6/ingest.py`'s
    `tool_completed` structured log line -- CloudWatch Logs Insights, not
    this DDB read path, is the source of truth for that number in
    production).
    """
    client = findings or FindingsClient()
    since = datetime.now(UTC) - timedelta(days=days_back)
    raw_findings, _ = client.list_page(feature_id="F6", since=since, limit=10_000)
    violations = [
        ShadowViolation.model_validate(item["payload"])
        for item in raw_findings
        if item.get("payload")
    ]
    return violations, len(raw_findings)


@sentinel_handler(feature_id="F6", tool_name="shadow_guard_report")
def shadow_guard_report(invocation: ParsedInvocation, _context: LambdaContext) -> dict[str, Any]:
    days_back = int(invocation.parameters.get("days_back", 7))
    severity_filter: Severity = invocation.parameters.get("severity_filter", "MEDIUM")

    violations, total_events_ingested = load_recent_violations(days_back=days_back)
    payload, controls = build_report(
        violations,
        days_back=days_back,
        severity_filter=severity_filter,
        total_events_ingested=total_events_ingested,
    )

    return {
        "payload": payload.model_dump(mode="json"),
        "compensating_controls": [control.model_dump(mode="json") for control in controls],
    }


def publish_weekly_report(
    payload: ShadowViolationPayload,
    controls: list[CompensatingControl],
    *,
    s3_client: S3Client | None = None,
) -> str:
    """Report persistence path (phase-07 §4 Step 4: `SentinelReports/f6/
    {year}-W{week}/report.json`). `adapters.s3.reports.ReportsClient` is
    documented read-only ("Writers are each specialist's own report
    Lambda" -- its own module docstring) and exposes no write method, so
    this writer calls boto3 directly -- the same "no adapter wraps this
    write path yet" exception F1's `tools/f1/scan.py` already established
    for IAM reads (agents/README.md §1's boundary note).
    """
    week_id = _week_id(datetime.now(UTC))
    key = f"f6/{week_id}/report.json"
    body = {
        "payload": payload.model_dump(mode="json"),
        "compensating_controls": [c.model_dump(mode="json") for c in controls],
    }
    client: S3Client = s3_client or boto3.client("s3", region_name=adapters_settings.region)
    client.put_object(
        Bucket=adapters_settings.reports_bucket,
        Key=key,
        Body=json.dumps(body, default=str).encode("utf-8"),
        ContentType="application/json",
    )
    return key
