from __future__ import annotations

import json
from typing import TYPE_CHECKING

import boto3
import pytest

from iam_sentinel_adapters.errors import ValidationError
from iam_sentinel_adapters.s3.reports import ReportsClient

if TYPE_CHECKING:
    from collections.abc import Iterator

_BUCKET = "sentinel-reports-test"
_REGION = "us-east-1"


@pytest.fixture
def reports_bucket(moto_session: None) -> Iterator[str]:
    s3 = boto3.client("s3", region_name=_REGION)
    s3.create_bucket(Bucket=_BUCKET)
    yield _BUCKET


def test_get_latest_cost_report_returns_none_when_empty(reports_bucket: str) -> None:
    client = ReportsClient(bucket=reports_bucket)

    assert client.get_latest_cost_report() is None


def test_get_latest_cost_report_picks_the_lexicographically_last_key(reports_bucket: str) -> None:
    s3 = boto3.client("s3", region_name=_REGION)
    s3.put_object(Bucket=reports_bucket, Key="cost/2026-W05.json", Body=json.dumps({"week": 5}))
    s3.put_object(Bucket=reports_bucket, Key="cost/2026-W12.json", Body=json.dumps({"week": 12}))
    client = ReportsClient(bucket=reports_bucket)

    result = client.get_latest_cost_report()

    assert result is not None
    key, body = result
    assert key == "cost/2026-W12.json"
    assert body == {"week": 12}


def test_get_latest_cost_report_rejects_malformed_json(reports_bucket: str) -> None:
    s3 = boto3.client("s3", region_name=_REGION)
    s3.put_object(Bucket=reports_bucket, Key="cost/2026-W01.json", Body=b"not json")
    client = ReportsClient(bucket=reports_bucket)

    with pytest.raises(ValidationError):
        client.get_latest_cost_report()


def test_get_latest_report_resolves_per_kind_prefix(reports_bucket: str) -> None:
    s3 = boto3.client("s3", region_name=_REGION)
    s3.put_object(Bucket=reports_bucket, Key="f6/2026-W05.json", Body=json.dumps({"kind": "f6"}))
    s3.put_object(
        Bucket=reports_bucket, Key="cost/2026-W12.json", Body=json.dumps({"kind": "cost"})
    )
    client = ReportsClient(bucket=reports_bucket)

    result = client.get_latest_report("f6")

    assert result == ("f6/2026-W05.json", {"kind": "f6"})


def test_get_latest_report_rejects_unknown_kind(reports_bucket: str) -> None:
    client = ReportsClient(bucket=reports_bucket)

    with pytest.raises(ValidationError):
        client.get_latest_report("not-a-kind")


def test_get_report_by_key_returns_none_when_missing(reports_bucket: str) -> None:
    client = ReportsClient(bucket=reports_bucket)

    assert client.get_report_by_key("f2/2026-W01.json") is None


def test_get_report_by_key_returns_the_exact_key(reports_bucket: str) -> None:
    s3 = boto3.client("s3", region_name=_REGION)
    s3.put_object(Bucket=reports_bucket, Key="f2/2026-W01.json", Body=json.dumps({"ok": True}))
    client = ReportsClient(bucket=reports_bucket)

    assert client.get_report_by_key("f2/2026-W01.json") == {"ok": True}
