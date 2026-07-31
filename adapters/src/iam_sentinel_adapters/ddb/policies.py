"""`SentinelPolicies` table client. Table key shape: PK `org_id`, SK
`policy_arn` (phase-05 SS4 Step 1). Goes through `DynamoDbHelper` like every
other table client (adapters/README.md SS1: boto3 only through adapters/).

Two consumers, unified into one item shape rather than two divergent ones:
F4 (SCP Impact Analyst, phase-05, the table's originally-planned first
consumer) caches each SCP's `DescribePolicy` result via `get`/`put` so
`scp_impact_walk_ou` doesn't re-fetch the same handful of SCPs on every deep
OU walk. F6 (Shadow Guard, phase-07) landed second and needs the same cache
plus an ordered root-to-account chain reconstruction (`get_chain`) and
staleness check (`is_stale`) -- both specialists were built in the same
parallel batch and independently wrote a client for this table before
either could see the other's work; reconciled at merge time into one
client with one item shape (`level`/`name`/`policy_document`/
`attached_targets`/`cached_at`/`ttl`) rather than risk two clients writing
incompatible attribute sets to the same DDB key. `get`/`put` keep F4's
exact original call signature and return shape (a bare `{arn, name,
document}` dict matching `PolicyRef.model_validate`) so
`tools/f4/walk_ou.py` needed zero changes; `put` defaults `level="ou"`
since F4 never tracked chain position, only individual policies.

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
        """Returns a bare `{arn, name, document}` dict (matching
        `PolicyRef.model_validate`), or `None` on a cache miss or an expired
        entry -- callers treat both identically (re-fetch via
        `organizations:DescribePolicy`).
        """
        item = self._helper.get_item({"org_id": org_id, "policy_arn": policy_arn})
        if item is None or self._is_expired(item):
            return None
        return {
            "arn": policy_arn,
            "name": item.get("name", policy_arn),
            "document": item.get("policy_document", {}),
        }

    def put(self, org_id: str, policy_arn: str, policy_ref: dict[str, Any]) -> None:
        self.put_policy(
            org_id,
            policy_arn,
            level="ou",
            name=str(policy_ref.get("name", policy_arn)),
            document=dict(policy_ref.get("document", {})),
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
        now = datetime.now(UTC)
        self._helper.put_item(
            {
                "org_id": org_id,
                "policy_arn": policy_arn,
                "level": level,
                "name": name,
                "policy_document": document,
                "attached_targets": attached_targets or [],
                "cached_at": now.isoformat(),
                "ttl": int((now + timedelta(minutes=_TTL_MINUTES)).timestamp()),
            }
        )

    def get_chain(self, org_id: str) -> list[dict[str, Any]]:
        """Reconstruct the ordered `[{level, policies: [...]}]` chain for
        `org_id` -- root first, then every OU, then account (if cached).
        Stale entries are still returned: the caller has the refresh-cadence
        context this client doesn't, and decides whether to trust a stale
        cache (see `is_stale`).
        """
        items = self._helper.query(
            key_condition_expression="org_id = :org_id",
            expression_attribute_values={":org_id": org_id},
            limit=1000,
        )
        by_level: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            level = str(item.get("level", "ou"))
            by_level.setdefault(level, []).append(
                {
                    "arn": item["policy_arn"],
                    "name": item.get("name", item["policy_arn"]),
                    "document": item.get("policy_document", {}),
                }
            )
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

    def _is_expired(self, item: dict[str, Any], *, now: datetime | None = None) -> bool:
        ttl = item.get("ttl")
        if ttl is None:
            return False
        current = now or datetime.now(UTC)
        return int(ttl) < int(current.timestamp())
