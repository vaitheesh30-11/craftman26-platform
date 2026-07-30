from __future__ import annotations

from typing import TYPE_CHECKING

from iam_sentinel_adapters.ddb.idempotency import IdempotencyClient

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

    from iam_sentinel_adapters.circuit_breaker import BreakerAccessor


def test_claim_succeeds_on_first_call(idempotency_table: Table, moto_breaker: BreakerAccessor) -> None:
    client = IdempotencyClient(table=idempotency_table, breaker=moto_breaker)

    assert client.claim("01JBP2VHF9K3Q0Z8R7X6M5N4A3") is True


def test_claim_rejects_a_repeat_correlation_id(
    idempotency_table: Table, moto_breaker: BreakerAccessor
) -> None:
    client = IdempotencyClient(table=idempotency_table, breaker=moto_breaker)
    client.claim("01JBP2VHF9K3Q0Z8R7X6M5N4A3")

    assert client.claim("01JBP2VHF9K3Q0Z8R7X6M5N4A3") is False


def test_already_claimed_reflects_claim_state(
    idempotency_table: Table, moto_breaker: BreakerAccessor
) -> None:
    client = IdempotencyClient(table=idempotency_table, breaker=moto_breaker)

    assert client.already_claimed("never-claimed") is False
    client.claim("never-claimed")
    assert client.already_claimed("never-claimed") is True
