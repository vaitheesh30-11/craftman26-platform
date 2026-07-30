"""Shared moto fixtures for the adapters module. Zero live AWS calls."""

from __future__ import annotations

from typing import TYPE_CHECKING

import boto3
import pytest
from moto import mock_aws

from iam_sentinel_adapters.circuit_breaker import BreakerAccessor

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


@pytest.fixture
def findings_table(moto_session: None) -> Table:
    ddb = boto3.resource("dynamodb", region_name=_REGION)
    ddb.create_table(
        TableName="SentinelFindings-test",
        KeySchema=[
            {"AttributeName": "account_id#feature_id", "KeyType": "HASH"},
            {"AttributeName": "finding_id#detected_at", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "account_id#feature_id", "AttributeType": "S"},
            {"AttributeName": "finding_id#detected_at", "AttributeType": "S"},
            {"AttributeName": "severity", "AttributeType": "S"},
            {"AttributeName": "detected_at", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "severity-index",
                "KeySchema": [
                    {"AttributeName": "severity", "KeyType": "HASH"},
                    {"AttributeName": "detected_at", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    return ddb.Table("SentinelFindings-test")


@pytest.fixture
def decisions_in_flight_table(moto_session: None) -> Table:
    ddb = boto3.resource("dynamodb", region_name=_REGION)
    ddb.create_table(
        TableName="SentinelDecisionsInFlight-test",
        KeySchema=[{"AttributeName": "correlation_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "correlation_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    return ddb.Table("SentinelDecisionsInFlight-test")


@pytest.fixture
def decisions_table(moto_session: None) -> Table:
    ddb = boto3.resource("dynamodb", region_name=_REGION)
    ddb.create_table(
        TableName="SentinelDecisions-test",
        KeySchema=[
            {"AttributeName": "principal", "KeyType": "HASH"},
            {"AttributeName": "decided_at", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "principal", "AttributeType": "S"},
            {"AttributeName": "decided_at", "AttributeType": "S"},
            {"AttributeName": "correlation_id", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "correlation-index",
                "KeySchema": [
                    {"AttributeName": "correlation_id", "KeyType": "HASH"},
                    {"AttributeName": "decided_at", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    return ddb.Table("SentinelDecisions-test")


@pytest.fixture
def faults_table(moto_session: None) -> Table:
    ddb = boto3.resource("dynamodb", region_name=_REGION)
    ddb.create_table(
        TableName="SentinelFaults-test",
        KeySchema=[
            {"AttributeName": "correlation_id", "KeyType": "HASH"},
            {"AttributeName": "detected_at", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "correlation_id", "AttributeType": "S"},
            {"AttributeName": "detected_at", "AttributeType": "S"},
            {"AttributeName": "fault_class", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "fault-class-index",
                "KeySchema": [
                    {"AttributeName": "fault_class", "KeyType": "HASH"},
                    {"AttributeName": "detected_at", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    return ddb.Table("SentinelFaults-test")


@pytest.fixture
def idempotency_table(moto_session: None) -> Table:
    ddb = boto3.resource("dynamodb", region_name=_REGION)
    ddb.create_table(
        TableName="SentinelIdempotency-test",
        KeySchema=[{"AttributeName": "correlation_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "correlation_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    return ddb.Table("SentinelIdempotency-test")


@pytest.fixture
def memory_episodic_table(moto_session: None) -> Table:
    ddb = boto3.resource("dynamodb", region_name=_REGION)
    ddb.create_table(
        TableName="SentinelMemoryEpisodic-test",
        KeySchema=[
            {"AttributeName": "principal", "KeyType": "HASH"},
            {"AttributeName": "decided_at", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "principal", "AttributeType": "S"},
            {"AttributeName": "decided_at", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    return ddb.Table("SentinelMemoryEpisodic-test")


@pytest.fixture
def memory_semantic_table(moto_session: None) -> Table:
    ddb = boto3.resource("dynamodb", region_name=_REGION)
    ddb.create_table(
        TableName="SentinelMemorySemantic-test",
        KeySchema=[
            {"AttributeName": "entity_kind", "KeyType": "HASH"},
            {"AttributeName": "entity_key", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "entity_kind", "AttributeType": "S"},
            {"AttributeName": "entity_key", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    return ddb.Table("SentinelMemorySemantic-test")


@pytest.fixture
def memory_procedural_table(moto_session: None) -> Table:
    ddb = boto3.resource("dynamodb", region_name=_REGION)
    ddb.create_table(
        TableName="SentinelMemoryProcedural-test",
        KeySchema=[
            {"AttributeName": "pattern_kind", "KeyType": "HASH"},
            {"AttributeName": "pattern_hash", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "pattern_kind", "AttributeType": "S"},
            {"AttributeName": "pattern_hash", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    return ddb.Table("SentinelMemoryProcedural-test")


@pytest.fixture
def connections_table(moto_session: None) -> Table:
    ddb = boto3.resource("dynamodb", region_name=_REGION)
    ddb.create_table(
        TableName="SentinelConnections-test",
        KeySchema=[{"AttributeName": "connection_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "connection_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    return ddb.Table("SentinelConnections-test")


@pytest.fixture
def moto_breaker(breakers_table: Table) -> BreakerAccessor:
    return BreakerAccessor(table=breakers_table)
