from __future__ import annotations

from typing import TYPE_CHECKING

from iam_sentinel_adapters.ddb.decisions_in_flight import DecisionsInFlightClient

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

    from iam_sentinel_adapters.circuit_breaker import BreakerAccessor


def test_start_then_get_round_trips(
    decisions_in_flight_table: Table, moto_breaker: BreakerAccessor
) -> None:
    client = DecisionsInFlightClient(table=decisions_in_flight_table, breaker=moto_breaker)

    client.start("corr-1", {"query": "audit passrole"})

    result = client.get("corr-1")
    assert result is not None
    assert result["query"] == "audit passrole"
    assert "expires_at" in result


def test_complete_removes_the_item(
    decisions_in_flight_table: Table, moto_breaker: BreakerAccessor
) -> None:
    client = DecisionsInFlightClient(table=decisions_in_flight_table, breaker=moto_breaker)
    client.start("corr-2", {})

    client.complete("corr-2")

    assert client.get("corr-2") is None


def test_complete_on_missing_correlation_is_idempotent(
    decisions_in_flight_table: Table, moto_breaker: BreakerAccessor
) -> None:
    client = DecisionsInFlightClient(table=decisions_in_flight_table, breaker=moto_breaker)

    client.complete("never-started")  # must not raise
