from __future__ import annotations

from typing import TYPE_CHECKING

from iam_sentinel_adapters.ddb.decisions import DecisionsClient

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

    from iam_sentinel_adapters.circuit_breaker import BreakerAccessor

_PRINCIPAL = "arn:aws:iam::111122223333:role/Auditor"


def test_put_then_latest_for_principal_round_trips(
    decisions_table: Table, moto_breaker: BreakerAccessor
) -> None:
    client = DecisionsClient(table=decisions_table, breaker=moto_breaker)
    client.put({"principal": _PRINCIPAL, "decided_at": "2026-07-30T12:00:00Z", "status": "ANSWERED"})

    latest = client.latest_for_principal(_PRINCIPAL)

    assert len(latest) == 1
    assert latest[0]["status"] == "ANSWERED"


def test_latest_for_principal_returns_most_recent_first(
    decisions_table: Table, moto_breaker: BreakerAccessor
) -> None:
    client = DecisionsClient(table=decisions_table, breaker=moto_breaker)
    client.put({"principal": _PRINCIPAL, "decided_at": "2026-07-30T12:00:00Z", "status": "ANSWERED"})
    client.put({"principal": _PRINCIPAL, "decided_at": "2026-07-30T13:00:00Z", "status": "ESCALATED"})

    latest = client.latest_for_principal(_PRINCIPAL, limit=1)

    assert latest[0]["status"] == "ESCALATED"


def test_query_since_filters_by_sort_key(decisions_table: Table, moto_breaker: BreakerAccessor) -> None:
    client = DecisionsClient(table=decisions_table, breaker=moto_breaker)
    client.put({"principal": _PRINCIPAL, "decided_at": "2026-07-29T00:00:00Z", "status": "ANSWERED"})
    client.put({"principal": _PRINCIPAL, "decided_at": "2026-07-30T13:00:00Z", "status": "ESCALATED"})

    results = client.query_since(_PRINCIPAL, "2026-07-30T00:00:00Z")

    assert len(results) == 1
    assert results[0]["status"] == "ESCALATED"
