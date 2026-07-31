"""passrole_scan — enumerate every `iam:PassRole` grant in a target account
(phase-02 §4 Step 1). Returns raw `PassRoleEdge`s only; multi-hop synthesis
and privilege classification of the *target* roles is `passrole_graph`'s
job (graph.py) -- this module never inspects a role's own permissions,
only the permissions of whoever holds the PassRole grant.

Calls boto3 IAM read APIs directly via `cross_account.assume()`'s returned
session -- the one deliberate exception to "boto3 only through adapters/"
(agents/README.md §1): `tools/common/cross_account.py`'s own docstring
names this exact use ("every specialist tool that reads a member account's
IAM... state goes through assume()"), and no `adapters/` package wraps IAM
read APIs (only ddb/evidence/kb/llm/security_hub/sns/zelkova exist there).
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, TYPE_CHECKING

from iam_sentinel_agents.contracts.passrole import PassRoleEdge
from iam_sentinel_agents.tools.common import cross_account
from iam_sentinel_agents.tools.common.runtime import sentinel_handler
from iam_sentinel_agents.tools.f1.wildcard import resolve_role_pattern

if TYPE_CHECKING:
    from collections.abc import Iterable

    import boto3
    from aws_lambda_powertools.utilities.typing import LambdaContext
    from mypy_boto3_iam.client import IAMClient

    from iam_sentinel_agents.contracts.common import FeatureID
    from iam_sentinel_agents.tools.common.event_parser import ParsedInvocation

# phase-02 §10 risk mitigation: bounded thread pool for GetPolicyVersion.
_MAX_CONCURRENT_POLICY_FETCHES = 10
# Condition keys/prefixes worth surfacing on a PassRoleEdge (phase-02 §4
# Step 1: PassedToService, PassedToServiceAllowsToken, aws:PrincipalTag/*).
_RELEVANT_CONDITION_PREFIXES = ("iam:passedtoservice", "aws:principaltag/")


def _list_principals(iam: IAMClient, principal_arn: str | None) -> list[dict[str, str]]:
    principals: list[dict[str, str]] = []
    for user_page in iam.get_paginator("list_users").paginate():
        principals.extend(
            {"type": "user", "name": user["UserName"], "arn": user["Arn"]}
            for user in user_page["Users"]
        )
    for role_page in iam.get_paginator("list_roles").paginate():
        principals.extend(
            {"type": "role", "name": role["RoleName"], "arn": role["Arn"]}
            for role in role_page["Roles"]
        )
    if principal_arn is not None:
        principals = [p for p in principals if p["arn"] == principal_arn]
    return principals


def _list_role_arns(iam: IAMClient) -> list[str]:
    return [
        role["Arn"] for page in iam.get_paginator("list_roles").paginate() for role in page["Roles"]
    ]


def normalize_policy_document(raw: Any) -> dict[str, Any]:
    """IAM's `PolicyDocument`/`Document` response fields are typed
    `str | PolicyDocumentDictTypeDef` in the boto3 stubs -- botocore's own
    IAM customization JSON-decodes them in practice, but the stub can't
    promise that, so callers must handle both shapes.
    """
    if isinstance(raw, str):
        return dict(json.loads(raw))
    return dict(raw)


def _inline_policy_documents(
    iam: IAMClient, principal: dict[str, str]
) -> list[tuple[str, dict[str, Any]]]:
    is_user = principal["type"] == "user"
    documents: list[tuple[str, dict[str, Any]]] = []
    policy_names: list[str] = []
    if is_user:
        for user_page in iam.get_paginator("list_user_policies").paginate(
            UserName=principal["name"]
        ):
            policy_names.extend(user_page["PolicyNames"])
    else:
        for role_page in iam.get_paginator("list_role_policies").paginate(
            RoleName=principal["name"]
        ):
            policy_names.extend(role_page["PolicyNames"])

    for policy_name in policy_names:
        response = (
            iam.get_user_policy(UserName=principal["name"], PolicyName=policy_name)
            if is_user
            else iam.get_role_policy(RoleName=principal["name"], PolicyName=policy_name)
        )
        synthetic_arn = f"arn:aws:iam::inline:{principal['type']}/{principal['name']}/{policy_name}"
        documents.append((synthetic_arn, normalize_policy_document(response["PolicyDocument"])))
    return documents


def _fetch_policy_document(iam: IAMClient, policy_arn: str) -> dict[str, Any]:
    policy = iam.get_policy(PolicyArn=policy_arn)["Policy"]
    version = iam.get_policy_version(PolicyArn=policy_arn, VersionId=policy["DefaultVersionId"])
    return normalize_policy_document(version["PolicyVersion"]["Document"])


def _attached_policy_arns(iam: IAMClient, principal: dict[str, str]) -> list[str]:
    is_user = principal["type"] == "user"
    policy_arns: list[str] = []
    if is_user:
        for user_page in iam.get_paginator("list_attached_user_policies").paginate(
            UserName=principal["name"]
        ):
            policy_arns.extend(attached["PolicyArn"] for attached in user_page["AttachedPolicies"])
    else:
        for role_page in iam.get_paginator("list_attached_role_policies").paginate(
            RoleName=principal["name"]
        ):
            policy_arns.extend(attached["PolicyArn"] for attached in role_page["AttachedPolicies"])
    return policy_arns


def _attached_policy_documents(
    iam: IAMClient,
    principal: dict[str, str],
    cache: dict[str, dict[str, Any]],
    pool: ThreadPoolExecutor,
) -> list[tuple[str, dict[str, Any]]]:
    policy_arns = _attached_policy_arns(iam, principal)

    missing = [arn for arn in policy_arns if arn not in cache]
    if missing:
        fetched = pool.map(lambda arn: (arn, _fetch_policy_document(iam, arn)), missing)
        for policy_arn, document in fetched:
            cache[policy_arn] = document
    return [(arn, cache[arn]) for arn in policy_arns]


def _statements(document: dict[str, Any]) -> list[dict[str, Any]]:
    statement = document.get("Statement", [])
    return [statement] if isinstance(statement, dict) else list(statement)


def _grants_passrole(statement: dict[str, Any]) -> bool:
    if statement.get("Effect") != "Allow":
        return False
    actions = statement.get("Action", [])
    if isinstance(actions, str):
        actions = [actions]
    normalized = {str(action).lower() for action in actions}
    return bool(normalized & {"iam:passrole", "iam:*", "*"})


def _summarize_conditions(condition: dict[str, Any]) -> dict[str, str]:
    summary: dict[str, str] = {}
    for operator_block in condition.values():
        if not isinstance(operator_block, dict):
            continue
        for key, value in operator_block.items():
            if key.lower().startswith(_RELEVANT_CONDITION_PREFIXES):
                summary[key] = value if isinstance(value, str) else ",".join(str(v) for v in value)
    return summary


def _edges_for_statement(
    *, from_principal_arn: str, statement: dict[str, Any], policy_arn: str, role_arns: list[str]
) -> list[PassRoleEdge]:
    resources = statement.get("Resource", [])
    if isinstance(resources, str):
        resources = [resources]
    condition_summary = _summarize_conditions(statement.get("Condition", {}))
    return [
        PassRoleEdge(
            from_principal=from_principal_arn,
            passable_role_pattern=pattern,
            resolved_role_arns=resolve_role_pattern(pattern, role_arns),
            condition_summary=condition_summary,
            grant_source_policy_arn=policy_arn,
            grant_statement_id=statement.get("Sid"),
        )
        for pattern in resources
    ]


def _edges_for_principal(
    iam: IAMClient,
    principal: dict[str, str],
    role_arns: list[str],
    policy_cache: dict[str, dict[str, Any]],
    pool: ThreadPoolExecutor,
) -> tuple[list[PassRoleEdge], int]:
    documents: Iterable[tuple[str, dict[str, Any]]] = [
        *_inline_policy_documents(iam, principal),
        *_attached_policy_documents(iam, principal, policy_cache, pool),
    ]
    edges: list[PassRoleEdge] = []
    policies_scanned = 0
    for policy_arn, document in documents:
        policies_scanned += 1
        for statement in _statements(document):
            if _grants_passrole(statement):
                edges.extend(
                    _edges_for_statement(
                        from_principal_arn=principal["arn"],
                        statement=statement,
                        policy_arn=policy_arn,
                        role_arns=role_arns,
                    )
                )
    return edges, policies_scanned


def scan_account(
    account_id: str,
    principal_arn: str | None,
    *,
    feature_id: FeatureID,
    correlation_id: str,
    session: boto3.Session | None = None,
) -> dict[str, Any]:
    """Core scan logic, independent of the Bedrock Lambda envelope.

    `session` is an injection point for tests (an already-scoped moto
    session) -- production always goes through `cross_account.assume()`.
    """
    start = time.monotonic()
    boto_session = session or cross_account.assume(
        account_id, feature_id=feature_id, correlation_id=correlation_id
    )
    iam: IAMClient = boto_session.client("iam")

    principals = _list_principals(iam, principal_arn)
    role_arns = _list_role_arns(iam)

    edges: list[PassRoleEdge] = []
    policies_scanned = 0
    policy_cache: dict[str, dict[str, Any]] = {}

    with ThreadPoolExecutor(max_workers=_MAX_CONCURRENT_POLICY_FETCHES) as pool:
        for principal in principals:
            principal_edges, principal_policy_count = _edges_for_principal(
                iam, principal, role_arns, policy_cache, pool
            )
            edges.extend(principal_edges)
            policies_scanned += principal_policy_count

    duration_ms = int((time.monotonic() - start) * 1000)
    return {
        "edges": [edge.model_dump(mode="json") for edge in edges],
        "principals_scanned": len(principals),
        "policies_scanned": policies_scanned,
        "scan_duration_ms": duration_ms,
    }


@sentinel_handler(feature_id="F1", tool_name="passrole_scan")
def passrole_scan(invocation: ParsedInvocation, _context: LambdaContext) -> dict[str, Any]:
    return scan_account(
        invocation.parameters["account_id"],
        invocation.parameters.get("principal_arn"),
        feature_id="F1",
        correlation_id=invocation.correlation_id,
    )
