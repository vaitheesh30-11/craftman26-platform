from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from iam_sentinel_adapters.ddb.findings import FindingsClient

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

    from iam_sentinel_adapters.circuit_breaker import BreakerAccessor


def _finding(**overrides: object) -> dict[str, object]:
    base = {
        "account_id": "111122223333",
        "feature_id": "F1",
        "finding_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
        "detected_at": "2026-07-30T00:00:00+00:00",
        "severity": "HIGH",
        "status": "OPEN",
    }
    base.update(overrides)
    return base


def test_put_then_get_round_trips(findings_table: Table, moto_breaker: BreakerAccessor) -> None:
    client = FindingsClient(table=findings_table, breaker=moto_breaker)
    finding = _finding()

    client.put(finding)
    result = client.get("111122223333", "F1", "01ARZ3NDEKTSV4RRFFQ69G5FAV")

    assert result is not None
    assert result["severity"] == "HIGH"


def test_get_missing_finding_returns_none(findings_table: Table, moto_breaker: BreakerAccessor) -> None:
    client = FindingsClient(table=findings_table, breaker=moto_breaker)

    assert client.get("111122223333", "F1", "nonexistent") is None


def test_query_by_severity_uses_the_gsi(findings_table: Table, moto_breaker: BreakerAccessor) -> None:
    client = FindingsClient(table=findings_table, breaker=moto_breaker)
    client.put(_finding(finding_id="a", severity="HIGH", detected_at="2026-07-30T00:00:00+00:00"))
    client.put(_finding(finding_id="b", severity="LOW", detected_at="2026-07-30T00:00:00+00:00"))

    results = client.query_by_severity("HIGH", since=datetime(2026, 1, 1, tzinfo=UTC))

    assert len(results) == 1
    assert results[0]["finding_id"] == "a"


def test_update_status_changes_the_stored_item(findings_table: Table, moto_breaker: BreakerAccessor) -> None:
    client = FindingsClient(table=findings_table, breaker=moto_breaker)
    client.put(_finding())

    client.update_status("111122223333", "F1", "01ARZ3NDEKTSV4RRFFQ69G5FAV", "RESOLVED")

    result = client.get("111122223333", "F1", "01ARZ3NDEKTSV4RRFFQ69G5FAV")
    assert result is not None
    assert result["status"] == "RESOLVED"


def test_update_status_on_missing_finding_raises(
    findings_table: Table, moto_breaker: BreakerAccessor
) -> None:
    client = FindingsClient(table=findings_table, breaker=moto_breaker)

    try:
        client.update_status("111122223333", "F1", "nonexistent", "RESOLVED")
    except KeyError:
        return
    raise AssertionError("expected KeyError")


def test_query_by_severity_filters_out_stale_findings(
    findings_table: Table, moto_breaker: BreakerAccessor
) -> None:
    client = FindingsClient(table=findings_table, breaker=moto_breaker)
    old_time = (datetime(2020, 1, 1, tzinfo=UTC)).isoformat()
    client.put(_finding(finding_id="old", severity="HIGH", detected_at=old_time))

    results = client.query_by_severity("HIGH", since=datetime.now(UTC) - timedelta(days=1))

    assert results == []
