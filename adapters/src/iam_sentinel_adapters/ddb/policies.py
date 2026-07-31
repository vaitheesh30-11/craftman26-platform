"""`SentinelPolicies` table client. Table key shape: PK `org_id`, SK
`policy_arn` (phase-05 SS4 Step 1). Goes through `DynamoDbHelper` like every
other table client (adapters/README.md SS1: boto3 only through adapters/).

Two consumers, unified into one item shape rather than two divergent ones:
F4 (SCP Impact Analyst, phase-05, the table's originally-planned first
consumer, already merged to `main`) caches each SCP's `DescribePolicy`
result via `get`/`put` so `scp_impact_walk_ou` doesn't re-fetch the same
handful of SCPs on every deep OU walk. F6 (Shadow Guard, phase-07) landed
second in the same parallel batch, before either specialist could see the
other's work, and needs the same cache plus an ordered root-to-account
chain reconstruction (`get_chain`) and staleness check (`is_stale`).
Reconciled at merge time (docs/decisions/0031) into one client, additive
over F4's already-merged, already-tested item shape rather than a second,
incompatible one: every item still carries F4's exact `policy_ref`/
`expires_at` attributes (so `get`/`put` and `tools/f4/walk_ou.py` needed
zero changes), and F6's `put_policy` adds `level`/`cached_at` alongside
them on the same item. `get_chain`/`is_stale` default a missing `level` to
`"ou"` and treat a missing `cached_at` as stale, so items F4 wrote via the
original `put()` (which never set either) are read safely rather than
crashing F6's chain walk.

Returns plain dicts, never an agents-side type -- module boundary (adapters
never imports from `agents/`).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal

from iam_sentinel_adapters.ddb.base import DynamoDbHelper
from iam_sentinel_adapters.settings import settings

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

    from iam_sentinel_adapters.circuit_breaker import BreakerAccessor

_TTL_MINUTES = 15
_LEVEL_ORDER = {"root": 0, "ou": 1, "account": 2}
PolicyLevel = Literal["root", "ou", "account"]


class PoliciesCacheClient:
    def __init__(
        self,
        *,
        table_name: str | None = None,
        table: Table | None = None,
        breaker: BreakerAccessor | None = None,
    ) -> None:
        self._helper = DynamoDbHelper(
            table_name or settings.policies_table, table=table, breaker=breaker
        )

    def get(self, org_id: str, policy_arn: str) -> dict[str, Any] | None:
        """Returns the cached `PolicyRef`-shaped dict, or `None` on a cache
        miss or an expired entry -- callers treat both identically (re-fetch
        via `organizations:DescribePolicy`). F4's exact original contract;
        unchanged by F6's additions below.
        """
        item = self._helper.get_item({"org_id": org_id, "policy_arn": policy_arn})
        if item is None:
            return None
        expires_at = item.get("expires_at")
        if expires_at is not None and int(expires_at) < int(datetime.now(UTC).timestamp()):
            return None
        policy_ref: dict[str, Any] = dict(item["policy_ref"])
        return policy_ref

    def put(self, org_id: str, policy_arn: str, policy_ref: dict[str, Any]) -> None:
        """F4's exact original contract. Does not set `level`/`cached_at`
        (F4 never tracked chain position) -- `get_chain`/`is_stale` default
        those to `"ou"`/stale respectively for items written this way.
        """
        expires_at = int((datetime.now(UTC) + timedelta(minutes=_TTL_MINUTES)).timestamp())
        self._helper.put_item(
            {
                "org_id": org_id,
                "policy_arn": policy_arn,
                "policy_ref": policy_ref,
                "expires_at": expires_at,
            }
        )

    def put_policy(
        self,
        org_id: str,
        policy_arn: str,
        *,
        level: PolicyLevel,
        name: str,
        document: dict[str, Any],
        attached_targets: list[str] | None = None,
    ) -> None:
        """F6's writer -- same item shape `get`/`put` read (`policy_ref`/
        `expires_at`), plus `level`/`cached_at` so `get_chain`/`is_stale`
        can reconstruct chain position and freshness without a second
        Organizations round-trip. `attached_targets` is accepted for a
        future consumer that needs it but not yet persisted as its own
        attribute -- no current reader asks for it back.
        """
        del attached_targets
        now = datetime.now(UTC)
        expires_at = int((now + timedelta(minutes=_TTL_MINUTES)).timestamp())
        self._helper.put_item(
            {
                "org_id": org_id,
                "policy_arn": policy_arn,
                "policy_ref": {"arn": policy_arn, "name": name, "document": document},
                "expires_at": expires_at,
                "level": level,
                "cached_at": now.isoformat(),
            }
        )

    def get_chain(self, org_id: str) -> list[dict[str, Any]]:
        """Reconstruct the ordered `[{level, policies: [...]}]` chain for
        `org_id` -- root first, then every OU, then account (if cached).
        Stale entries are still returned: the caller has the refresh-cadence
        context this client doesn't, and decides whether to trust a stale
        cache (see `is_stale`). An item with no `expires_at` past window is
        NOT re-checked for expiry here -- `get_chain` is F6's own read path,
        independent of `get`'s per-key expiry semantics.
        """
        items = self._helper.query(
            key_condition_expression="org_id = :org_id",
            expression_attribute_values={":org_id": org_id},
            limit=1000,
        )
        by_level: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            level = str(item.get("level", "ou"))
            policy_ref = item.get("policy_ref") or {
                "arn": item["policy_arn"],
                "name": item["policy_arn"],
                "document": {},
            }
            by_level.setdefault(level, []).append(dict(policy_ref))
        return [
            {"level": level, "policies": policies}
            for level, policies in sorted(
                by_level.items(), key=lambda kv: _LEVEL_ORDER.get(kv[0], 99)
            )
        ]

    def is_stale(self, org_id: str, *, now: datetime | None = None) -> bool:
        items = self._helper.query(
            key_condition_expression="org_id = :org_id",
            expression_attribute_values={":org_id": org_id},
            limit=1,
        )
        if not items:
            return True
        cached_at_raw = items[0].get("cached_at")
        if not isinstance(cached_at_raw, str):
            return True
        cached_at = datetime.fromisoformat(cached_at_raw)
        current = now or datetime.now(UTC)
        return current - cached_at > timedelta(minutes=_TTL_MINUTES)
