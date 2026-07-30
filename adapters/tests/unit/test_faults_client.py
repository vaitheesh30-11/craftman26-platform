from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from iam_sentinel_adapters.ddb.faults import FaultsClient

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

    from iam_sentinel_adapters.circuit_breaker import BreakerAccessor


def _fault(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "correlation_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
        "fault_class": "transient_throttling",
        "origin": "FindingsClient",
        "action_taken": "retried",
        "detail": "throttled twice, third attempt succeeded",
        "detected_at": "2026-07-30T00:00:00+00:00",
    }
    base.update(overrides)
    return base


def test_put_then_list_by_fault_class(faults_table: Table, moto_breaker: BreakerAccessor) -> None:
    client = FaultsClient(table=faults_table, breaker=moto_breaker)
    client.put(_fault())
    client.put(_fault(correlation_id="other", fault_class="model_fault"))

    items, next_key = client.list_recent(fault_class="transient_throttling")

    assert len(items) == 1
    assert items[0]["origin"] == "FindingsClient"
    assert next_key is None


def test_list_recent_filters_by_since_via_scan(
    faults_table: Table, moto_breaker: BreakerAccessor
) -> None:
    client = FaultsClient(table=faults_table, breaker=moto_breaker)
    old_time = datetime(2020, 1, 1, tzinfo=UTC).isoformat()
    client.put(_fault(detected_at=old_time))

    items, _ = client.list_recent(since=datetime.now(UTC) - timedelta(days=1))

    assert items == []


def test_list_recent_with_no_filters_scans_everything(
    faults_table: Table, moto_breaker: BreakerAccessor
) -> None:
    client = FaultsClient(table=faults_table, breaker=moto_breaker)
    client.put(_fault())

    items, _ = client.list_recent()

    assert len(items) == 1
