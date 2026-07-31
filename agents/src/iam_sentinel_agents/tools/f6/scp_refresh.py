"""shadow_guard_scp_refresh -- phase-07 §4 Step 2's 15-minute cache
refresh ("Refresh every 15 min via a scheduled Lambda
shadow_guard_scp_refresh").

Not agent-callable (EventBridge scheduled rule target, same category as
`shadow_guard_ingest`) -- no `sentinel_handler` envelope parsing applies
here either. Calls `organizations:ListRoots` /
`ListOrganizationalUnitsForParent` / `ListPoliciesForTarget` /
`DescribePolicy` directly via boto3 (§7's IAM policy resource is `"*"`,
same-account reads against the management account this Lambda already
runs in -- no `cross_account.assume()` hop needed, unlike every F1-style
member-account read). No `adapters/` package wraps Organizations read
APIs, matching the identical "boto3 only through adapters/ -- with IAM/
Organizations read APIs as the one deliberate exception" precedent
`tools/f1/scan.py`'s own docstring already established.
"""

from __future__ import annotations

import json
from typing import Any, Literal, TYPE_CHECKING

import boto3
from iam_sentinel_adapters.ddb.policies import PoliciesCacheClient

from iam_sentinel_agents.settings import settings

if TYPE_CHECKING:
    from aws_lambda_powertools.utilities.typing import LambdaContext
    from mypy_boto3_organizations.client import OrganizationsClient

_SCP_FILTER: Literal["SERVICE_CONTROL_POLICY"] = "SERVICE_CONTROL_POLICY"


def _root_id(org: OrganizationsClient) -> str:
    roots = org.list_roots()["Roots"]
    return str(roots[0]["Id"])


def _child_ou_ids(org: OrganizationsClient, parent_id: str) -> list[str]:
    ou_ids: list[str] = []
    for page in org.get_paginator("list_organizational_units_for_parent").paginate(
        ParentId=parent_id
    ):
        ou_ids.extend(str(ou["Id"]) for ou in page["OrganizationalUnits"])
    return ou_ids


def _walk_all_ou_ids(org: OrganizationsClient, root_id: str) -> list[str]:
    """Breadth-first walk of every OU under root (phase-07 §4 Step 2:
    "union-of-root-and-all-OU-levels"). Bounded by an explicit visited set
    -- Organizations' OU tree is a DAG-free tree by construction, but a
    defensive bound costs nothing and matches phase-02's "abort rather than
    let an org blow up an unbounded walk" convention.
    """
    all_ou_ids: list[str] = []
    frontier = [root_id]
    visited: set[str] = set()
    while frontier:
        parent_id = frontier.pop()
        if parent_id in visited:
            continue
        visited.add(parent_id)
        children = _child_ou_ids(org, parent_id)
        all_ou_ids.extend(children)
        frontier.extend(children)
    return all_ou_ids


def _policies_for_target(org: OrganizationsClient, target_id: str) -> list[dict[str, Any]]:
    # `page["Policies"]` is `list[PolicySummaryTypeDef]`, not `list[dict[str,
    # Any]]` -- mypy --strict treats TypedDicts as structurally distinct
    # from a bare `dict[str, Any]` list, so `policy_summaries` is typed
    # `list[Any]` here and re-narrowed via subscripting below (the boto3
    # stubs still enforce real keys on each `summary`).
    policy_summaries: list[Any] = []
    for page in org.get_paginator("list_policies_for_target").paginate(
        TargetId=target_id, Filter=_SCP_FILTER
    ):
        policy_summaries.extend(page["Policies"])

    resolved: list[dict[str, Any]] = []
    for summary in policy_summaries:
        described = org.describe_policy(PolicyId=summary["Id"])["Policy"]
        content = described["Content"]
        resolved.append(
            {
                "arn": summary["Arn"],
                "name": summary["Name"],
                "document": json.loads(content) if isinstance(content, str) else content,
            }
        )
    return resolved


def refresh_scp_cache(
    *,
    org_id: str,
    organizations_client: OrganizationsClient | None = None,
    policies: PoliciesCacheClient | None = None,
) -> dict[str, int]:
    """Core refresh logic, independent of the Lambda envelope -- takes an
    injected `organizations_client` so tests exercise it against a
    boto3-stubber double without a real Organizations account (moto's
    Organizations support does not model `ListPoliciesForTarget` /
    `DescribePolicy` for SCPs as of this phase; see docs/decisions/0023).
    """
    org: OrganizationsClient = organizations_client or boto3.client(
        "organizations", region_name=settings.region
    )
    policies_client = policies or PoliciesCacheClient()

    root_id = _root_id(org)
    ou_ids = _walk_all_ou_ids(org, root_id)

    levels_cached = 0
    policies_cached = 0
    for target_id, level in [(root_id, "root"), *((ou_id, "ou") for ou_id in ou_ids)]:
        for policy in _policies_for_target(org, target_id):
            policies_client.put_policy(
                org_id,
                policy["arn"],
                level=level,  # type: ignore[arg-type]
                name=policy["name"],
                document=policy["document"],
                attached_targets=[target_id],
            )
            policies_cached += 1
        levels_cached += 1

    return {"levels_cached": levels_cached, "policies_cached": policies_cached}


def handler(event: dict[str, Any], context: LambdaContext) -> dict[str, int]:
    _ = event, context
    return refresh_scp_cache(org_id=settings.mgmt_org_id)
