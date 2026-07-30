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


def test_cancel_sets_canceled_without_clobbering_the_dispatch_payload(
    decisions_in_flight_table: Table, moto_breaker: BreakerAccessor
) -> None:
    client = DecisionsInFlightClient(table=decisions_in_flight_table, breaker=moto_breaker)
    client.start("corr-3", {"query": "audit passrole"})

    client.cancel("corr-3")

    result = client.get("corr-3")
    assert result is not None
    assert result["canceled"] is True
    assert result["query"] == "audit passrole"


def test_is_canceled_reflects_cancel_state(
    decisions_in_flight_table: Table, moto_breaker: BreakerAccessor
) -> None:
    client = DecisionsInFlightClient(table=decisions_in_flight_table, breaker=moto_breaker)
    client.start("corr-4", {})
    assert client.is_canceled("corr-4") is False

    client.cancel("corr-4")

    assert client.is_canceled("corr-4") is True


def test_is_canceled_on_missing_correlation_is_false(
    decisions_in_flight_table: Table, moto_breaker: BreakerAccessor
) -> None:
    client = DecisionsInFlightClient(table=decisions_in_flight_table, breaker=moto_breaker)

    assert client.is_canceled("never-started") is False
