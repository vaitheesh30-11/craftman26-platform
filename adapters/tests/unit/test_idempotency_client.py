from __future__ import annotations

from typing import TYPE_CHECKING

from iam_sentinel_adapters.ddb.idempotency import IdempotencyClient

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

    from iam_sentinel_adapters.circuit_breaker import BreakerAccessor


def test_claim_succeeds_on_first_call(
    idempotency_table: Table, moto_breaker: BreakerAccessor
) -> None:
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


def test_claim_for_result_then_store_result_round_trips(
    idempotency_table: Table, moto_breaker: BreakerAccessor
) -> None:
    client = IdempotencyClient(table=idempotency_table, breaker=moto_breaker)
    key = "approval-key-1"

    assert client.claim_for_result(key, input_hash="hash-1") is True
    assert client.get_record(key) == {
        "correlation_id": key,
        "input_hash": "hash-1",
        "status": "RUNNING",
        "claimed_at": client.get_record(key)["claimed_at"],
        "expires_at": client.get_record(key)["expires_at"],
    }

    client.store_result(key, input_hash="hash-1", status="COMPLETED", result={"state": "SUCCEEDED"})

    record = client.get_record(key)
    assert record["status"] == "COMPLETED"
    assert record["result"] == {"state": "SUCCEEDED"}


def test_claim_for_result_rejects_a_repeat_key(
    idempotency_table: Table, moto_breaker: BreakerAccessor
) -> None:
    client = IdempotencyClient(table=idempotency_table, breaker=moto_breaker)

    assert client.claim_for_result("approval-key-2", input_hash="hash-a") is True
    assert client.claim_for_result("approval-key-2", input_hash="hash-a") is False
