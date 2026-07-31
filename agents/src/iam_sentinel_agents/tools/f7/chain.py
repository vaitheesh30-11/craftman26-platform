"""Walk the root -> ... -> account SCP chain (phase-08 §4 Step 1).

Unlike F1's `tools/common/cross_account.assume()` pattern, this module calls
`organizations` directly against the caller's own credentials -- AWS
Organizations is an org-wide control-plane API (it has no per-member-account
endpoint to assume into), and phase-08 §7's own IAM policy section says so
explicitly: "No cross-account role needed." The Lambda's execution role is
granted `organizations:ListParents`/`ListPoliciesForTarget`/`DescribePolicy`
directly.
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

import boto3

from iam_sentinel_agents.tools.common.scp_engine import (
    normalize_policy_document,
    ScpLevel,
    ScpLevelChain,
    ScpPolicy,
)

if TYPE_CHECKING:
    from mypy_boto3_organizations.client import OrganizationsClient

_SCP_FILTER = "SERVICE_CONTROL_POLICY"
_ROOT_TYPE = "ROOT"
# phase-08 §10 risk mitigation footprint: an org chain is at most a handful
# of levels deep in practice; bounding the climb prevents an unbounded loop
# if Organizations ever returned a cyclic/malformed parent chain.
_MAX_CHAIN_DEPTH = 32


def _climb_to_root(org: OrganizationsClient, account_id: str) -> list[tuple[str, ScpLevel]]:
    """Returns [(target_id, level), ...] ordered account -> ... -> root
    (the reverse of the chain the engine wants; caller reverses it).
    """
    chain: list[tuple[str, ScpLevel]] = [(account_id, "account")]
    current_id = account_id
    for _ in range(_MAX_CHAIN_DEPTH):
        parents = org.list_parents(ChildId=current_id)["Parents"]
        if not parents:
            break
        parent = parents[0]
        parent_id = parent["Id"]
        level: ScpLevel = "root" if parent.get("Type") == _ROOT_TYPE else "ou"
        chain.append((parent_id, level))
        current_id = parent_id
        if level == "root":
            break
    return chain


def _policies_for_target(org: OrganizationsClient, target_id: str) -> list[ScpPolicy]:
    policies: list[ScpPolicy] = []
    paginator = org.get_paginator("list_policies_for_target")
    for page in paginator.paginate(TargetId=target_id, Filter=_SCP_FILTER):  # type: ignore[arg-type]
        for summary in page["Policies"]:
            policy_id = summary["Id"]
            described = org.describe_policy(PolicyId=policy_id)["Policy"]
            content: Any = described.get("Content", "{}")
            policies.append(
                ScpPolicy(
                    policy_id=policy_id,
                    name=summary.get("Name", policy_id),
                    arn=summary.get("Arn", policy_id),
                    document=normalize_policy_document(content),
                )
            )
    return policies


def walk_scp_chain(
    account_id: str,
    *,
    organizations_client: OrganizationsClient | None = None,
    session: boto3.Session | None = None,
) -> list[ScpLevelChain]:
    """Returns the chain ordered root -> ... -> account, each level's
    `ScpPolicy` documents fully resolved -- ready for
    `scp_engine.compute_effective_policy`.
    """
    org = organizations_client
    if org is None:
        boto_session = session
        if boto_session is None:
            boto_session = boto3.Session()
        org = boto_session.client("organizations")

    account_up_to_root = _climb_to_root(org, account_id)
    root_down_to_account = list(reversed(account_up_to_root))

    return [
        ScpLevelChain(
            level=level, target_id=target_id, policies=_policies_for_target(org, target_id)
        )
        for target_id, level in root_down_to_account
    ]
