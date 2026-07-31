"""repair/scp_cache_stale -- §7's third repair Lambda.

"Trigger: SentinelPoliciesStale metric. Duties: Bulk refresh all cached
SCPs." Delegates to `tools.f6.scp_refresh.refresh_scp_cache` -- F6 already
built the exact "walk root + every OU, re-`DescribePolicy`, write into
`PoliciesCacheClient`" logic this repair action needs (it is F6's own
15-minute scheduled refresh, `shadow_guard_scp_refresh`); this module does
not reimplement it, it just wraps that call with the repair-Lambda
obligations §7's closing line requires (an `EvidenceRecord(kind=
"repair_action")` and a `FaultRecord(action_taken="auto_repaired")`) that
F6's own scheduled refresh has no reason to emit on its own routine cadence.
"""

from __future__ import annotations

from datetime import datetime, UTC
from typing import Any, TYPE_CHECKING

from iam_sentinel_adapters.evidence import EvidenceClient

from iam_sentinel_agents.tools.common.retry import record_fault
from iam_sentinel_agents.tools.f6.scp_refresh import refresh_scp_cache

if TYPE_CHECKING:
    from aws_lambda_powertools.utilities.typing import LambdaContext
    from iam_sentinel_adapters.ddb.faults import FaultsClient
    from iam_sentinel_adapters.ddb.policies import PoliciesCacheClient
    from mypy_boto3_organizations.client import OrganizationsClient


def repair_scp_cache_stale(
    *,
    org_id: str,
    correlation_id: str = "repair-scp-cache-stale",
    organizations_client: OrganizationsClient | None = None,
    policies_client: PoliciesCacheClient | None = None,
    evidence_client: EvidenceClient | None = None,
    faults_client: FaultsClient | None = None,
) -> dict[str, Any]:
    result = refresh_scp_cache(
        org_id=org_id, organizations_client=organizations_client, policies=policies_client
    )

    body = {"org_id": org_id, **result}
    (evidence_client or EvidenceClient()).put_signed_evidence(
        kind="repair_action", body=body, correlation_id=correlation_id, feature_id="F6"
    )
    record_fault(
        correlation_id=correlation_id,
        fault_class="data_corruption",
        origin="repair:scp_cache_stale",
        action_taken="auto_repaired",
        detail=f"bulk-refreshed SCP cache for org_id={org_id}: {result}",
        resolved_at=datetime.now(UTC),
        faults_client=faults_client,
        force_write=True,
    )
    return body


def scp_cache_stale_repair(event: dict[str, Any], _context: LambdaContext) -> dict[str, Any]:
    """Alarm-action Lambda entrypoint (§7 trigger: `SentinelPoliciesStale`
    metric)."""
    return repair_scp_cache_stale(org_id=event["org_id"])
