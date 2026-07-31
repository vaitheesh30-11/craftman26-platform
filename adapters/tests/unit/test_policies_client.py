"""`PoliciesCacheClient` (`ddb/policies.py`) -- covers both F4's original
`get`/`put` contract and F6's `put_policy`/`get_chain`/`is_stale` additions
against a real (moto-backed) `SentinelPolicies` table. See
docs/decisions/0031 §"Merge-time reconciliation" for why this one client
now serves both specialists.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from iam_sentinel_adapters.ddb.policies import PoliciesCacheClient

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

    from iam_sentinel_adapters.circuit_breaker import BreakerAccessor


def test_put_then_get_round_trips(policies_table: Table, moto_breaker: BreakerAccessor) -> None:
    client = PoliciesCacheClient(table=policies_table, breaker=moto_breaker)
    client.put(
        "o-1",
        "arn:aws:organizations::o-1:policy/p-1",
        {"name": "FullAWSAccess", "document": {"Statement": []}},
    )

    result = client.get("o-1", "arn:aws:organizations::o-1:policy/p-1")

    assert result == {
        "arn": "arn:aws:organizations::o-1:policy/p-1",
        "name": "FullAWSAccess",
        "document": {"Statement": []},
    }


def test_get_missing_policy_returns_none(
    policies_table: Table, moto_breaker: BreakerAccessor
) -> None:
    client = PoliciesCacheClient(table=policies_table, breaker=moto_breaker)

    assert client.get("o-1", "arn:aws:organizations::o-1:policy/nonexistent") is None


def test_get_expired_entry_returns_none(
    policies_table: Table, moto_breaker: BreakerAccessor
) -> None:
    client = PoliciesCacheClient(table=policies_table, breaker=moto_breaker)
    already_expired_ttl = int((datetime.now(UTC) - timedelta(minutes=1)).timestamp())
    policies_table.put_item(
        Item={
            "org_id": "o-1",
            "policy_arn": "arn:aws:organizations::o-1:policy/p-1",
            "level": "root",
            "name": "FullAWSAccess",
            "policy_document": {"Statement": []},
            "attached_targets": [],
            "cached_at": (datetime.now(UTC) - timedelta(minutes=20)).isoformat(),
            "ttl": already_expired_ttl,
        }
    )

    result = client.get("o-1", "arn:aws:organizations::o-1:policy/p-1")

    assert result is None


def test_put_defaults_to_ou_level(policies_table: Table, moto_breaker: BreakerAccessor) -> None:
    client = PoliciesCacheClient(table=policies_table, breaker=moto_breaker)
    client.put("o-1", "arn:aws:organizations::o-1:policy/p-1", {"name": "X", "document": {}})

    item = policies_table.get_item(
        Key={"org_id": "o-1", "policy_arn": "arn:aws:organizations::o-1:policy/p-1"}
    )["Item"]

    assert item["level"] == "ou"


def test_get_chain_orders_root_before_ou_before_account(
    policies_table: Table, moto_breaker: BreakerAccessor
) -> None:
    client = PoliciesCacheClient(table=policies_table, breaker=moto_breaker)
    client.put_policy(
        "o-1", "arn:...:p-account", level="account", name="AcctPolicy", document={}
    )
    client.put_policy("o-1", "arn:...:p-root", level="root", name="RootPolicy", document={})
    client.put_policy("o-1", "arn:...:p-ou", level="ou", name="OuPolicy", document={})

    chain = client.get_chain("o-1")

    assert [entry["level"] for entry in chain] == ["root", "ou", "account"]
    assert chain[0]["policies"][0]["name"] == "RootPolicy"


def test_get_chain_returns_empty_list_for_unknown_org(
    policies_table: Table, moto_breaker: BreakerAccessor
) -> None:
    client = PoliciesCacheClient(table=policies_table, breaker=moto_breaker)

    assert client.get_chain("o-unknown") == []


def test_is_stale_true_when_no_cache_entries(
    policies_table: Table, moto_breaker: BreakerAccessor
) -> None:
    client = PoliciesCacheClient(table=policies_table, breaker=moto_breaker)

    assert client.is_stale("o-1") is True


def test_is_stale_false_within_ttl_window(
    policies_table: Table, moto_breaker: BreakerAccessor
) -> None:
    client = PoliciesCacheClient(table=policies_table, breaker=moto_breaker)
    client.put_policy("o-1", "arn:...:p-root", level="root", name="RootPolicy", document={})

    assert client.is_stale("o-1") is False


def test_is_stale_true_after_ttl_elapses(
    policies_table: Table, moto_breaker: BreakerAccessor
) -> None:
    client = PoliciesCacheClient(table=policies_table, breaker=moto_breaker)
    client.put_policy("o-1", "arn:...:p-root", level="root", name="RootPolicy", document={})

    later = datetime.now(UTC) + timedelta(minutes=16)

    assert client.is_stale("o-1", now=later) is True
