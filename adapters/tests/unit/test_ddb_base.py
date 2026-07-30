from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from iam_sentinel_adapters.ddb.base import DynamoDbHelper
from iam_sentinel_adapters.errors import CircuitOpenError, ValidationError

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

    from iam_sentinel_adapters.circuit_breaker import BreakerAccessor


def test_put_then_get_round_trips(breakers_table: Table, moto_breaker: BreakerAccessor) -> None:
    import boto3

    ddb = boto3.resource("dynamodb", region_name="us-east-1")
    ddb.create_table(
        TableName="TestTable",
        KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    table = ddb.Table("TestTable")
    helper = DynamoDbHelper("TestTable", table=table, breaker=moto_breaker)

    helper.put_item({"pk": "a", "value": 1})

    assert helper.get_item({"pk": "a"}) == {"pk": "a", "value": 1}


def test_get_missing_item_returns_none(breakers_table: Table, moto_breaker: BreakerAccessor) -> None:
    import boto3

    ddb = boto3.resource("dynamodb", region_name="us-east-1")
    ddb.create_table(
        TableName="TestTable2",
        KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    table = ddb.Table("TestTable2")
    helper = DynamoDbHelper("TestTable2", table=table, breaker=moto_breaker)

    assert helper.get_item({"pk": "missing"}) is None


def test_conditional_put_failure_raises_validation_error(
    breakers_table: Table, moto_breaker: BreakerAccessor
) -> None:
    import boto3

    ddb = boto3.resource("dynamodb", region_name="us-east-1")
    ddb.create_table(
        TableName="TestTable3",
        KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    table = ddb.Table("TestTable3")
    helper = DynamoDbHelper("TestTable3", table=table, breaker=moto_breaker)
    helper.put_item({"pk": "a"})

    with pytest.raises(ValidationError):
        helper.put_item({"pk": "a"}, condition_expression="attribute_not_exists(pk)")


def test_open_breaker_short_circuits_before_any_ddb_call(
    breakers_table: Table, moto_breaker: BreakerAccessor
) -> None:
    moto_breaker.trip("SomeTable", reason="test")
    helper = DynamoDbHelper("SomeTable", table=None, breaker=moto_breaker)  # type: ignore[arg-type]

    with pytest.raises(CircuitOpenError):
        helper.get_item({"pk": "a"})


def test_delete_then_get_returns_none(breakers_table: Table, moto_breaker: BreakerAccessor) -> None:
    import boto3

    ddb = boto3.resource("dynamodb", region_name="us-east-1")
    ddb.create_table(
        TableName="TestTable4",
        KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    table = ddb.Table("TestTable4")
    helper = DynamoDbHelper("TestTable4", table=table, breaker=moto_breaker)
    helper.put_item({"pk": "a"})

    helper.delete_item({"pk": "a"})

    assert helper.get_item({"pk": "a"}) is None
