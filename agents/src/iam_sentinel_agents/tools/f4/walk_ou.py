"""scp_impact_walk_ou -- phase-05 SS4 Step 1: walk the SCP chain from root
down to the target OU/account.

Unlike every F1 tool, this Lambda never calls `cross_account.assume()`:
`organizations:*` read APIs only succeed when called with credentials that
belong to the organization's management account (or a registered delegated
administrator) -- there is no per-member-account role to assume into for
org-wide Organizations data, so this tool's execution role itself carries
the read policy from phase-05 SS7. See docs/decisions/0023.
"""

from __future__ import annotations

import json
from typing import Any, Literal, TYPE_CHECKING

import boto3

from iam_sentinel_agents.settings import settings
from iam_sentinel_agents.tools.common.runtime import sentinel_handler
from iam_sentinel_agents.tools.common.scp_policy_evaluator import LevelPolicies, PolicyRef

if TYPE_CHECKING:
    from aws_lambda_powertools.utilities.typing import LambdaContext
    from iam_sentinel_adapters.ddb.policies import PoliciesCacheClient
    from mypy_boto3_organizations.client import OrganizationsClient

    from iam_sentinel_agents.tools.common.event_parser import ParsedInvocation

_POLICY_FILTER: Literal["SERVICE_CONTROL_POLICY"] = "SERVICE_CONTROL_POLICY"
_Level = Literal["root", "ou", "account"]
_LEVEL_BY_NODE_TYPE: dict[str, _Level] = {
    "ROOT": "root",
    "ORGANIZATIONAL_UNIT": "ou",
    "ACCOUNT": "account",
}


def _target_node_type(target: str) -> str:
    if target.startswith("r-"):
        return "ROOT"
    if target.startswith("ou-"):
        return "ORGANIZATIONAL_UNIT"
    return "ACCOUNT"


def ancestor_chain(org_client: OrganizationsClient, target: str) -> list[tuple[str, str]]:
    """`[(id, node_type), ...]` ordered root -> ... -> target (inclusive).

    `organizations:ListParents` only returns a node's immediate parent, so
    the full path is rebuilt by walking upward one hop at a time until a
    ROOT-typed parent is reached.
    """
    chain: list[tuple[str, str]] = [(target, _target_node_type(target))]
    while chain[0][1] != "ROOT":
        parents = org_client.list_parents(ChildId=chain[0][0])["Parents"]
        if not parents:
            break
        parent = parents[0]
        chain.insert(0, (parent["Id"], parent["Type"]))
    return chain


def _resolve_policy(
    org_client: OrganizationsClient,
    policy_id: str,
    policy_arn: str,
    *,
    org_id: str,
    cache: PoliciesCacheClient | None,
) -> PolicyRef:
    if cache is not None:
        cached = cache.get(org_id, policy_arn)
        if cached is not None:
            return PolicyRef.model_validate(cached)
    described = org_client.describe_policy(PolicyId=policy_id)["Policy"]
    ref = PolicyRef(
        arn=described["PolicySummary"]["Arn"],
        name=described["PolicySummary"]["Name"],
        document=json.loads(described["Content"]),
    )
    if cache is not None:
        cache.put(org_id, policy_arn, ref.model_dump(mode="json"))
    return ref


def _policies_for_node(
    org_client: OrganizationsClient, node_id: str, *, org_id: str, cache: PoliciesCacheClient | None
) -> list[PolicyRef]:
    refs: list[PolicyRef] = []
    for page in org_client.get_paginator("list_policies_for_target").paginate(
        TargetId=node_id, Filter=_POLICY_FILTER
    ):
        for summary in page["Policies"]:
            refs.append(
                _resolve_policy(
                    org_client, summary["Id"], summary["Arn"], org_id=org_id, cache=cache
                )
            )
    return refs


def walk_chain(
    target: str,
    *,
    org_client: OrganizationsClient,
    org_id: str,
    policies_cache: PoliciesCacheClient | None = None,
) -> list[LevelPolicies]:
    """Core walk logic, independent of the Bedrock Lambda envelope.
    `org_client`/`policies_cache` are the injection points tests use.
    """
    ancestors = ancestor_chain(org_client, target)
    return [
        LevelPolicies(
            level=_LEVEL_BY_NODE_TYPE[node_type],
            target=node_id,
            policies=_policies_for_node(org_client, node_id, org_id=org_id, cache=policies_cache),
        )
        for node_id, node_type in ancestors
    ]


@sentinel_handler(feature_id="F4", tool_name="scp_impact_walk_ou")
def scp_impact_walk_ou(invocation: ParsedInvocation, _context: LambdaContext) -> dict[str, Any]:
    from iam_sentinel_adapters.ddb.policies import PoliciesCacheClient

    target = invocation.parameters["target"]
    org: OrganizationsClient = boto3.client("organizations", region_name=settings.region)
    org_id = org.describe_organization()["Organization"]["Id"]
    chain = walk_chain(target, org_client=org, org_id=org_id, policies_cache=PoliciesCacheClient())
    return {"chain": [level.model_dump(mode="json") for level in chain]}
