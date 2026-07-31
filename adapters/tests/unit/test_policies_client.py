"""`PoliciesCacheClient` (`ddb/policies.py`) -- F4's original `get`/`put`
contract plus F6's `put_policy`/`get_chain`/`is_stale` additions, against a
real (moto-backed) `SentinelPolicies` table. See docs/decisions/0031
"Merge-time reconciliation" for why this one client now serves both
specialists on one item shape.
"""

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


def test_put_policy_round_trips_via_get(
    policies_table: Table, moto_breaker: BreakerAccessor
) -> None:
    client = PoliciesCacheClient(table=policies_table, breaker=moto_breaker)
    client.put_policy(
        _ORG_ID, _POLICY_ARN, level="root", name="FullAWSAccess", document={"Statement": []}
    )

    result = client.get(_ORG_ID, _POLICY_ARN)

    assert result == {
        "arn": _POLICY_ARN,
        "name": "FullAWSAccess",
        "document": {"Statement": []},
    }


def test_get_chain_orders_root_before_ou_before_account(
    policies_table: Table, moto_breaker: BreakerAccessor
) -> None:
    client = PoliciesCacheClient(table=policies_table, breaker=moto_breaker)
    client.put_policy(_ORG_ID, "arn:...:p-account", level="account", name="AcctPolicy", document={})
    client.put_policy(_ORG_ID, "arn:...:p-root", level="root", name="RootPolicy", document={})
    client.put_policy(_ORG_ID, "arn:...:p-ou", level="ou", name="OuPolicy", document={})

    chain = client.get_chain(_ORG_ID)

    assert [entry["level"] for entry in chain] == ["root", "ou", "account"]
    assert chain[0]["policies"][0]["name"] == "RootPolicy"


def test_get_chain_defaults_a_put_written_item_to_ou_level(
    policies_table: Table, moto_breaker: BreakerAccessor
) -> None:
    """An item written by F4's original `put()` (no `level` attribute) must
    still surface in `get_chain` rather than being silently dropped --
    reconciliation must not break F4's existing write path.
    """
    client = PoliciesCacheClient(table=policies_table, breaker=moto_breaker)
    client.put(_ORG_ID, _POLICY_ARN, _POLICY_REF)

    chain = client.get_chain(_ORG_ID)

    assert chain == [{"level": "ou", "policies": [_POLICY_REF]}]


def test_get_chain_returns_empty_list_for_unknown_org(
    policies_table: Table, moto_breaker: BreakerAccessor
) -> None:
    client = PoliciesCacheClient(table=policies_table, breaker=moto_breaker)

    assert client.get_chain("o-unknown") == []


def test_is_stale_true_when_no_cache_entries(
    policies_table: Table, moto_breaker: BreakerAccessor
) -> None:
    client = PoliciesCacheClient(table=policies_table, breaker=moto_breaker)

    assert client.is_stale(_ORG_ID) is True


def test_is_stale_false_within_ttl_window(
    policies_table: Table, moto_breaker: BreakerAccessor
) -> None:
    client = PoliciesCacheClient(table=policies_table, breaker=moto_breaker)
    client.put_policy(_ORG_ID, "arn:...:p-root", level="root", name="RootPolicy", document={})

    assert client.is_stale(_ORG_ID) is False


def test_is_stale_true_after_ttl_elapses(
    policies_table: Table, moto_breaker: BreakerAccessor
) -> None:
    client = PoliciesCacheClient(table=policies_table, breaker=moto_breaker)
    client.put_policy(_ORG_ID, "arn:...:p-root", level="root", name="RootPolicy", document={})

    later = datetime.now(UTC) + timedelta(minutes=16)

    assert client.is_stale(_ORG_ID, now=later) is True


def test_is_stale_true_for_a_put_written_item_with_no_cached_at(
    policies_table: Table, moto_breaker: BreakerAccessor
) -> None:
    """F4's `put()` never sets `cached_at` -- `is_stale` must treat that as
    stale rather than raising on a missing attribute.
    """
    client = PoliciesCacheClient(table=policies_table, breaker=moto_breaker)
    client.put(_ORG_ID, _POLICY_ARN, _POLICY_REF)

    assert client.is_stale(_ORG_ID) is True
