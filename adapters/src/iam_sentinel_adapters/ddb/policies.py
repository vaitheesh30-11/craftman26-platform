"""`SentinelPolicies` table client (phase-05 SS4 Step 1) -- caches each SCP's
`DescribePolicy` result (name + JSON document) per organization for 15
minutes so `scp_impact_walk_ou` doesn't re-fetch (and re-parse) the same
handful of SCPs -- typically `FullAWSAccess` plus a small number of
organization-authored policies -- on every walk of a deep OU tree that
shares ancestors across many targets in a single turn.

Table key shape per phase-05 SS4 Step 1: PK `org_id`, SK `policy_arn`. Goes
through `DynamoDbHelper` like every other table client (adapters/README.md
SS1: boto3 only through adapters/).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from iam_sentinel_adapters.ddb.base import DynamoDbHelper
from iam_sentinel_adapters.settings import settings

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

    from iam_sentinel_adapters.circuit_breaker import BreakerAccessor

_TTL_MINUTES = 15


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
        via `organizations:DescribePolicy`).
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
        expires_at = int((datetime.now(UTC) + timedelta(minutes=_TTL_MINUTES)).timestamp())
        self._helper.put_item(
            {
                "org_id": org_id,
                "policy_arn": policy_arn,
                "policy_ref": policy_ref,
                "expires_at": expires_at,
            }
        )
