from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from iam_sentinel_adapters.ddb.policies import PoliciesCacheClient

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

    from iam_sentinel_adapters.circuit_breaker import BreakerAccessor

_ORG_ID = "o-abc123"
_POLICY_ARN = "arn:aws:organizations::123456789012:policy/o-abc123/service_control_policy/p-deny"
_POLICY_REF = {"arn": _POLICY_ARN, "name": "DenyTerminate", "document": {"Version": "2012-10-17"}}


def test_get_returns_none_on_a_cache_miss(
    policies_table: Table, moto_breaker: BreakerAccessor
) -> None:
    client = PoliciesCacheClient(table=policies_table, breaker=moto_breaker)

    assert client.get(_ORG_ID, _POLICY_ARN) is None


def test_put_then_get_round_trips_the_policy_ref(
    policies_table: Table, moto_breaker: BreakerAccessor
) -> None:
    client = PoliciesCacheClient(table=policies_table, breaker=moto_breaker)
    client.put(_ORG_ID, _POLICY_ARN, _POLICY_REF)

    assert client.get(_ORG_ID, _POLICY_ARN) == _POLICY_REF


def test_get_treats_an_expired_entry_as_a_miss(
    policies_table: Table, moto_breaker: BreakerAccessor
) -> None:
    client = PoliciesCacheClient(table=policies_table, breaker=moto_breaker)
    expired_at = int((datetime.now(UTC) - timedelta(minutes=1)).timestamp())
    policies_table.put_item(
        Item={
            "org_id": _ORG_ID,
            "policy_arn": _POLICY_ARN,
            "policy_ref": _POLICY_REF,
            "expires_at": expired_at,
        }
    )

    assert client.get(_ORG_ID, _POLICY_ARN) is None
