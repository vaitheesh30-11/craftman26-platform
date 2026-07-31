"""Moto DDB table provisioning shared by tools/f5 tests. Not a test module
itself (leading underscore keeps pytest from collecting it) -- must be
called from *inside* an active `@mock_aws` context, since these are plain
helper functions, not pytest fixtures (a fixture would resolve before the
decorated test function's own `with mock_aws():` block starts).
"""

from __future__ import annotations

from typing import Any

import boto3
from iam_sentinel_adapters.circuit_breaker import BreakerAccessor


def revocations_table() -> Any:
    ddb = boto3.resource("dynamodb", region_name="us-east-1")
    return ddb.create_table(
        TableName="SentinelRevocations-test",
        KeySchema=[
            {"AttributeName": "account_id", "KeyType": "HASH"},
            {"AttributeName": "role_arn", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "account_id", "AttributeType": "S"},
            {"AttributeName": "role_arn", "AttributeType": "S"},
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
