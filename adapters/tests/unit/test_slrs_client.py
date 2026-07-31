from __future__ import annotations

from typing import TYPE_CHECKING

from iam_sentinel_adapters.ddb.slrs import SlrsClient

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

    from iam_sentinel_adapters.circuit_breaker import BreakerAccessor


def _row(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "service_principal": "autoscaling.amazonaws.com",
        "slr_name": "AWSServiceRoleForAutoScaling",
        "required_actions": ["ec2:TerminateInstances"],
        "optional_actions": [],
        "core_actions": ["ec2:TerminateInstances"],
        "db_version": "1",
    }
    base.update(overrides)
    return base


def test_put_then_get_round_trips(slrs_table: Table, moto_breaker: BreakerAccessor) -> None:
    client = SlrsClient(table=slrs_table, breaker=moto_breaker)
    client.put(_row())

    result = client.get("autoscaling.amazonaws.com")

    assert result is not None
    assert result["slr_name"] == "AWSServiceRoleForAutoScaling"


def test_get_missing_row_returns_none(slrs_table: Table, moto_breaker: BreakerAccessor) -> None:
    client = SlrsClient(table=slrs_table, breaker=moto_breaker)

    assert client.get("nonexistent.amazonaws.com") is None


def test_list_all_returns_every_row(slrs_table: Table, moto_breaker: BreakerAccessor) -> None:
    client = SlrsClient(table=slrs_table, breaker=moto_breaker)
    client.put(_row(service_principal="autoscaling.amazonaws.com"))
    client.put(_row(service_principal="ecs.amazonaws.com", slr_name="AWSServiceRoleForECS"))

    rows = client.list_all()

    assert {row["service_principal"] for row in rows} == {
        "autoscaling.amazonaws.com",
        "ecs.amazonaws.com",
    }
