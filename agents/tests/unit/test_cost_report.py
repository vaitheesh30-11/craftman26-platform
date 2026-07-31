from __future__ import annotations

import json
from datetime import datetime, UTC
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from iam_sentinel_agents.tools.common import cost_report

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table


def _row(
    *,
    correlation_id: str = "corr-1",
    kind: str = "bedrock_dollars",
    amount: str = "0.10",
    feature_id: str = "F1",
    principal: str = "arn:aws:iam::111122223333:user/a",
    mode: str = "fast",
) -> dict[str, str]:
    return {
        "correlation_id": correlation_id,
        "kind": kind,
        "amount": amount,
        "feature_id": feature_id,
        "principal": principal,
        "mode": mode,
    }


def test_top_principals_ranks_by_dollars_descending() -> None:
    rows = [
        _row(principal="p1", amount="0.10"),
        _row(principal="p2", amount="0.90"),
        _row(principal="p1", amount="0.05"),
    ]

    result = cost_report.top_principals(rows)

    assert result[0] == {"principal": "p2", "dollars": 0.9}
    assert result[1] == {"principal": "p1", "dollars": 0.15}


def test_top_principals_respects_limit() -> None:
    rows = [_row(principal=f"p{i}", amount="0.01") for i in range(15)]

    result = cost_report.top_principals(rows, limit=10)

    assert len(result) == 10


def test_cost_per_feature_sums_only_dollar_kinds() -> None:
    rows = [
        _row(feature_id="F1", kind="bedrock_dollars", amount="0.10"),
        _row(feature_id="F1", kind="athena_dollars", amount="0.02"),
        _row(feature_id="F1", kind="bedrock_input_tokens", amount="500"),
        _row(feature_id="F2", kind="bedrock_dollars", amount="0.20"),
    ]

    result = cost_report.cost_per_feature(rows)

    assert result == {"F1": 0.12, "F2": 0.20}


def test_cost_per_feature_excludes_daily_ledger_rows_to_avoid_double_counting() -> None:
    rows = [
        _row(kind="bedrock_dollars", amount="0.10"),
        _row(kind="principal_daily_dollars", amount="0.10"),
    ]

    result = cost_report.cost_per_feature(rows)

    assert result == {"F1": 0.10}


def test_cost_per_finding_divides_by_finding_count() -> None:
    result = cost_report.cost_per_finding({"F1": 1.0, "F2": 2.0}, {"F1": 4, "F2": 0})

    assert result == {"F1": 0.25, "F2": 0.0}


def test_fast_slow_split_buckets_by_mode() -> None:
    rows = [
        _row(mode="fast", amount="0.01"),
        _row(mode="slow_single", amount="0.10"),
        _row(mode="slow_multi", amount="0.30"),
    ]

    result = cost_report.fast_slow_split(rows)

    assert result == {"fast": 0.01, "slow": 0.40}


def test_shadow_overhead_sums_shadow_mode_rows_only() -> None:
    rows = [_row(mode="fast", amount="0.01"), _row(mode="shadow", amount="0.05")]

    assert cost_report.shadow_overhead(rows) == 0.05


def test_build_report_produces_all_five_breakdowns() -> None:
    rows = [
        _row(principal="p1", feature_id="F1", mode="fast", amount="0.01"),
        _row(principal="p2", feature_id="F2", mode="slow_multi", amount="0.30"),
    ]
    generated_at = datetime(2026, 7, 27, tzinfo=UTC)  # ISO week 2026-W31

    report = cost_report.build_report(
        rows, finding_counts_by_feature={"F1": 2}, generated_at=generated_at
    )

    assert report.week_id == "2026-W31"
    assert report.cost_per_feature == {"F1": 0.01, "F2": 0.30}
    assert report.cost_per_finding["F1"] == 0.005
    assert report.fast_slow_split == {"fast": 0.01, "slow": 0.30}
    assert len(report.top_principals) == 2


def test_scan_all_samples_paginates(budget_table: Table) -> None:
    for i in range(3):
        budget_table.put_item(
            Item={
                "correlation_id": f"corr-{i}",
                "sample_id": f"s{i}",
                "kind": "bedrock_dollars",
                "amount": "0.01",
                "feature_id": "F1",
                "principal": "p1",
                "mode": "fast",
            }
        )

    rows = cost_report.scan_all_samples(budget_table)

    assert len(rows) == 3


def test_publish_weekly_report_writes_expected_key() -> None:
    """Key shape (`cost/{year}-W{week}.json`) is dictated by
    `adapters.s3.reports.ReportsClient._prefix_for_kind` (already exercised
    end-to-end in adapters/tests/unit/test_reports_client.py) -- this test
    only asserts this writer produces that exact shape, matching
    `tools/f6/report.py::test_publish_weekly_report_writes_to_the_reports_bucket`'s
    own MagicMock-client convention.
    """
    report = cost_report.build_report([], generated_at=datetime(2026, 7, 27, tzinfo=UTC))
    s3_client = MagicMock()

    key = cost_report.publish_weekly_report(report, s3_client=s3_client)

    assert key == "cost/2026-W31.json"
    put_kwargs = s3_client.put_object.call_args.kwargs
    assert put_kwargs["Key"] == "cost/2026-W31.json"
    body = json.loads(put_kwargs["Body"])
    assert body["week_id"] == "2026-W31"
