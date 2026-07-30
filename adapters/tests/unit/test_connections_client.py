from __future__ import annotations

from typing import TYPE_CHECKING

from iam_sentinel_adapters.ddb.connections import ConnectionsClient

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

    from iam_sentinel_adapters.circuit_breaker import BreakerAccessor


def test_connect_then_get_round_trips(
    connections_table: Table, moto_breaker: BreakerAccessor
) -> None:
    client = ConnectionsClient(table=connections_table, breaker=moto_breaker)

    client.connect(
        connection_id="conn-1",
        principal="arn:aws:sts::111111111111:assumed-role/Foo/bar",
        session_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
        auth_kind="cognito",
    )

    result = client.get("conn-1")
    assert result is not None
    assert result["principal"] == "arn:aws:sts::111111111111:assumed-role/Foo/bar"
    assert result["session_id"] == "01ARZ3NDEKTSV4RRFFQ69G5FAV"
    assert result["auth_kind"] == "cognito"
    assert "expires_at" in result


def test_get_missing_connection_returns_none(
    connections_table: Table, moto_breaker: BreakerAccessor
) -> None:
    client = ConnectionsClient(table=connections_table, breaker=moto_breaker)

    assert client.get("never-connected") is None


def test_disconnect_removes_the_row(
    connections_table: Table, moto_breaker: BreakerAccessor
) -> None:
    client = ConnectionsClient(table=connections_table, breaker=moto_breaker)
    client.connect(connection_id="conn-2", principal="p", session_id="s")

    client.disconnect("conn-2")

    assert client.get("conn-2") is None


def test_disconnect_on_missing_connection_is_idempotent(
    connections_table: Table, moto_breaker: BreakerAccessor
) -> None:
    client = ConnectionsClient(table=connections_table, breaker=moto_breaker)

    client.disconnect("never-connected")  # must not raise
