"""data_event_merge — phase-04 §4 Step 6 + SAFETY clause."""

from __future__ import annotations

from typing import Any

import pytest

from iam_sentinel_agents.contracts.data_event import S3DataEventUsage
from iam_sentinel_agents.tools.f3.merge import merge_policy

pytestmark = pytest.mark.unit

_BASE_POLICY: dict[str, Any] = {
    "Version": "2012-10-17",
    "Statement": [
        {"Effect": "Allow", "Action": "s3:ListBucket", "Resource": "arn:aws:s3:::reports"}
    ],
}


def _usage(**overrides: Any) -> S3DataEventUsage:
    defaults: dict[str, Any] = {
        "action": "s3:GetObject",
        "bucket": "reports",
        "prefixes": ["2026/01/a.json"],
        "consolidated_prefix": "2026/*",
        "call_count": 42,
    }
    defaults.update(overrides)
    return S3DataEventUsage(**defaults)


def test_merge_appends_a_scoped_statement_per_usage_entry() -> None:
    result = merge_policy(_BASE_POLICY, [_usage()])

    statements = result["merged_policy"]["Statement"]
    assert statements[0] == _BASE_POLICY["Statement"][0]
    assert statements[1] == {
        "Effect": "Allow",
        "Action": "s3:GetObject",
        "Resource": "arn:aws:s3:::reports/2026/*",
    }
    assert result["truncated"] is False


def test_merge_dedupes_same_action_into_a_resource_list() -> None:
    usage = [
        _usage(bucket="bucket-a", consolidated_prefix="a/*"),
        _usage(bucket="bucket-b", consolidated_prefix="b/*"),
    ]
    result = merge_policy({"Version": "2012-10-17", "Statement": []}, usage)

    statements = result["merged_policy"]["Statement"]
    assert len(statements) == 1
    assert statements[0]["Action"] == "s3:GetObject"
    assert sorted(statements[0]["Resource"]) == [
        "arn:aws:s3:::bucket-a/a/*",
        "arn:aws:s3:::bucket-b/b/*",
    ]


def test_merge_rejects_a_bare_wildcard_resource_and_falls_back_to_base() -> None:
    base_with_wildcard: dict[str, Any] = {
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow", "Action": "s3:GetObject", "Resource": "*"}],
    }

    result = merge_policy(base_with_wildcard, [_usage()])

    assert result["truncated"] is True
    assert result["merged_policy"]["Statement"] == base_with_wildcard["Statement"]


def test_merge_marks_truncated_when_over_the_inline_byte_cap() -> None:
    usage = [
        _usage(bucket=f"bucket-{i:04d}", consolidated_prefix=f"very/long/nested/prefix/{i:04d}/*")
        for i in range(300)
    ]

    result = merge_policy({"Version": "2012-10-17", "Statement": []}, usage)

    assert result["merged_policy_bytes"] > 6_144
    assert result["truncated"] is True
