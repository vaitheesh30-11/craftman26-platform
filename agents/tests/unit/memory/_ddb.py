"""Moto DDB table provisioning shared by tools/memory tests. Not a test
module itself -- must be called from inside an active `@mock_aws` context.
Mirrors `agents/tests/unit/f5/_ddb.py`'s convention.
"""

from __future__ import annotations

from typing import Any

import boto3
from iam_sentinel_adapters.circuit_breaker import BreakerAccessor
from iam_sentinel_adapters.memory.client import MemoryClient


def episodic_table() -> Any:
    ddb = boto3.resource("dynamodb", region_name="us-east-1")
    return ddb.create_table(
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


def semantic_table() -> Any:
    ddb = boto3.resource("dynamodb", region_name="us-east-1")
    return ddb.create_table(
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


def procedural_table() -> Any:
    ddb = boto3.resource("dynamodb", region_name="us-east-1")
    return ddb.create_table(
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


def breaker() -> BreakerAccessor:
    ddb = boto3.resource("dynamodb", region_name="us-east-1")
    ddb.create_table(
        TableName="SentinelBreakers-test",
        KeySchema=[{"AttributeName": "breaker_name", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "breaker_name", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    return BreakerAccessor(table=ddb.Table("SentinelBreakers-test"))


def memory_client() -> MemoryClient:
    return MemoryClient(
        episodic_table=episodic_table(),
        semantic_table=semantic_table(),
        procedural_table=procedural_table(),
        breaker=breaker(),
    )
