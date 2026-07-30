"""Shared moto fixtures for the adapters module. Zero live AWS calls."""

from __future__ import annotations

from typing import TYPE_CHECKING

import boto3
import pytest
from moto import mock_aws

if TYPE_CHECKING:
    from collections.abc import Iterator

    from mypy_boto3_dynamodb.service_resource import Table

_REGION = "us-east-1"


@pytest.fixture
def aws_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", _REGION)


@pytest.fixture
def moto_session(aws_credentials: None) -> Iterator[None]:
    with mock_aws():
        yield


@pytest.fixture
def breakers_table(moto_session: None) -> Table:
    ddb = boto3.resource("dynamodb", region_name=_REGION)
    ddb.create_table(
        TableName="SentinelBreakers-test",
        KeySchema=[{"AttributeName": "breaker_name", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "breaker_name", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    return ddb.Table("SentinelBreakers-test")


@pytest.fixture
def budget_table(moto_session: None) -> Table:
    ddb = boto3.resource("dynamodb", region_name=_REGION)
    ddb.create_table(
        TableName="SentinelBudget-test",
        KeySchema=[
            {"AttributeName": "correlation_id", "KeyType": "HASH"},
            {"AttributeName": "sample_id", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "correlation_id", "AttributeType": "S"},
            {"AttributeName": "sample_id", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    return ddb.Table("SentinelBudget-test")


@pytest.fixture
def ssm_client(moto_session: None) -> boto3.client:
    return boto3.client("ssm", region_name=_REGION)
