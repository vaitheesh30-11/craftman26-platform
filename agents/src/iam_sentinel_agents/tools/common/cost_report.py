"""cost_report_weekly -- weekly cost-attribution report Lambda
(agents-phase-16 §2, §5 step 7, docs/decisions/0033).

Scheduled, not agent-callable, mirroring `tools/f8/refresh.py`'s "plain
EventBridge-scheduled Lambda handler, no `sentinel_handler` envelope"
pattern -- a cross-feature cost rollup has no single `FeatureID` to tag it
with, so it does not fit `sentinel_handler`'s per-feature contract.

Aggregation (`build_report`) is pure -- it takes already-fetched
attribution rows (`CostMeter.samples()`-shaped dicts) and a per-feature
finding count, and produces a `WeeklyCostReport`. The DDB scan and the S3
write are the handler's own concern, same split F6's
`load_recent_violations` / `build_report` / `publish_weekly_report`
already established for `tools/f6/report.py`.

`adapters.s3.reports.ReportsClient` is documented read-only (its own
module docstring literally names this Lambda as the writer it's waiting
on) -- so, like `tools/f6/report.py::publish_weekly_report`, this module
calls `boto3` directly for the write. The exact key shape
(`cost/{year}-W{week}.json`) is dictated by `ReportsClient._prefix_for_kind`
and is exercised end-to-end in `adapters/tests/unit/test_reports_client.py`.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, UTC
from typing import Any, TYPE_CHECKING

import boto3
from iam_sentinel_adapters.settings import settings as adapter_settings

from iam_sentinel_agents.contracts.budget import WeeklyCostReport

if TYPE_CHECKING:
    from collections.abc import Iterable

    from aws_lambda_powertools.utilities.typing import LambdaContext
    from mypy_boto3_dynamodb.service_resource import Table
    from mypy_boto3_s3 import S3Client

_TOP_PRINCIPALS_LIMIT = 10
_DOLLAR_KINDS = frozenset({"bedrock_dollars", "athena_dollars", "principal_daily_dollars"})
_SLOW_MODES = frozenset({"slow_single", "slow_multi"})


def _week_id(when: datetime) -> str:
    iso_year, iso_week, _ = when.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def _dollar_amount(row: dict[str, str]) -> float:
    """`principal_daily_dollars` rows are `budget_gate`'s own daily-cap
    ledger keyed under a synthetic `daily#<principal>#<date>` correlation
    id (docs/decisions/0033) -- excluded here so the report doesn't
    double-count every request's estimated spend once under its real
    correlation id and again under its daily bucket.
    """
    if row.get("kind") == "principal_daily_dollars":
        return 0.0
    if row.get("kind") not in _DOLLAR_KINDS:
        return 0.0
    try:
        return float(row.get("amount", "0"))
    except ValueError:
        return 0.0


def top_principals(
    rows: Iterable[dict[str, str]], *, limit: int = _TOP_PRINCIPALS_LIMIT
) -> list[dict[str, float | str]]:
    totals: dict[str, float] = defaultdict(float)
    for row in rows:
        totals[row.get("principal", "unknown")] += _dollar_amount(row)
    ranked = sorted(totals.items(), key=lambda pair: pair[1], reverse=True)
    return [{"principal": principal, "dollars": round(dollars, 6)} for principal, dollars in ranked[:limit]]


def cost_per_feature(rows: Iterable[dict[str, str]]) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for row in rows:
        totals[row.get("feature_id", "unknown")] += _dollar_amount(row)
    return {feature: round(dollars, 6) for feature, dollars in totals.items()}


def cost_per_finding(
    cost_by_feature: dict[str, float], finding_counts_by_feature: dict[str, int]
) -> dict[str, float]:
    result: dict[str, float] = {}
    for feature, dollars in cost_by_feature.items():
        count = finding_counts_by_feature.get(feature, 0)
        result[feature] = round(dollars / count, 6) if count > 0 else 0.0
    return result


def fast_slow_split(rows: Iterable[dict[str, str]]) -> dict[str, float]:
    totals = {"fast": 0.0, "slow": 0.0}
    for row in rows:
        amount = _dollar_amount(row)
        if amount == 0.0:
            continue
        totals["slow" if row.get("mode") in _SLOW_MODES else "fast"] += amount
    return {mode: round(dollars, 6) for mode, dollars in totals.items()}


def shadow_overhead(rows: Iterable[dict[str, str]]) -> float:
    return round(sum(_dollar_amount(row) for row in rows if row.get("mode") == "shadow"), 6)


def build_report(
    rows: list[dict[str, str]],
    *,
    finding_counts_by_feature: dict[str, int] | None = None,
    week_id: str | None = None,
    generated_at: datetime | None = None,
) -> WeeklyCostReport:
    """Pure aggregation -- phase-16 §5 step 7's five required breakdowns."""
    now = generated_at or datetime.now(UTC)
    by_feature = cost_per_feature(rows)
    return WeeklyCostReport(
        week_id=week_id or _week_id(now),
        top_principals=top_principals(rows),
        cost_per_feature=by_feature,
        cost_per_finding=cost_per_finding(by_feature, finding_counts_by_feature or {}),
        fast_slow_split=fast_slow_split(rows),
        shadow_overhead_dollars=shadow_overhead(rows),
        generated_at=now,
    )


def scan_all_samples(table: Table) -> list[dict[str, str]]:
    """Full-table scan -- `SentinelBudget`'s partition key is
    `correlation_id`, which gives no cross-correlation query path, so a
    weekly batch report has no cheaper option than scanning everything
    written since the last report ran (acceptable at weekly-batch, not
    per-request, frequency).
    """
    rows: list[dict[str, str]] = []
    scan_kwargs: dict[str, Any] = {}
    while True:
        response = table.scan(**scan_kwargs)
        rows.extend({str(k): str(v) for k, v in item.items()} for item in response.get("Items", []))
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break
        scan_kwargs["ExclusiveStartKey"] = last_key
    return rows


def publish_weekly_report(report: WeeklyCostReport, *, s3_client: S3Client | None = None) -> str:
    key = f"cost/{report.week_id}.json"
    client: S3Client = s3_client or boto3.client("s3", region_name=adapter_settings.region)
    client.put_object(
        Bucket=adapter_settings.reports_bucket,
        Key=key,
        Body=json.dumps(report.model_dump(mode="json"), default=str).encode("utf-8"),
        ContentType="application/json",
    )
    return key


def cost_report_weekly(_event: dict[str, Any], _context: LambdaContext) -> dict[str, Any]:
    table: Table = boto3.resource(
        "dynamodb", region_name=adapter_settings.region
    ).Table(adapter_settings.budget_table)
    rows = scan_all_samples(table)
    report = build_report(rows)
    key = publish_weekly_report(report)
    return {"key": key, "report": report.model_dump(mode="json")}
