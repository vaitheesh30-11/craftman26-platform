"""Role-privilege classification for the blast-radius severity rubric
(phase-02 §3.3): given a role's own attached-managed-policy ARNs and its
inline + attached policy statements, classify the maximum privilege that
role grants.

Managed-policy-name shortcuts are checked first (the common case: someone
attached `AdministratorAccess`/`PowerUserAccess` directly); falls back to
statement-level inspection for custom policies achieving the same effect.
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from iam_sentinel_agents.contracts.passrole import ReachedPrivilege

_SENSITIVE_SERVICE_PREFIXES = ("kms:", "secretsmanager:")
_SENSITIVE_ACTIONS = frozenset({"s3:putbucketpolicy", "sts:assumerole"})


def _normalized_actions(statement: dict[str, Any]) -> set[str]:
    actions = statement.get("Action", [])
    if isinstance(actions, str):
        actions = [actions]
    return {str(action).lower() for action in actions}


def _resource_is_wildcard(statement: dict[str, Any]) -> bool:
    resources = statement.get("Resource", [])
    if isinstance(resources, str):
        resources = [resources]
    return "*" in resources


def _is_admin_policy_arn(policy_arn: str) -> bool:
    return policy_arn.endswith(":policy/AdministratorAccess")


def _is_power_user_policy_arn(policy_arn: str) -> bool:
    return policy_arn.endswith(":policy/PowerUserAccess")


def _is_iam_write_action(action: str) -> bool:
    return action == "iam:createrole" or (action.startswith("iam:") and "policy" in action)


def _has_admin_equivalent_statement(allow_statements: list[dict[str, Any]]) -> bool:
    return any(
        "*" in _normalized_actions(statement) and _resource_is_wildcard(statement)
        for statement in allow_statements
    )


def _has_iam_write_statement(allow_statements: list[dict[str, Any]]) -> bool:
    return any(
        any(_is_iam_write_action(action) for action in _normalized_actions(statement))
        for statement in allow_statements
    )


def _has_sensitive_service_statement(allow_statements: list[dict[str, Any]]) -> bool:
    for statement in allow_statements:
        actions = _normalized_actions(statement)
        if any(action.startswith(_SENSITIVE_SERVICE_PREFIXES) for action in actions):
            return True
        if actions & _SENSITIVE_ACTIONS:
            return True
    return False


def classify_role_privilege(
    *, attached_policy_arns: list[str], statements: list[dict[str, Any]]
) -> ReachedPrivilege:
    allow_statements = [s for s in statements if s.get("Effect") == "Allow"]

    if any(
        _is_admin_policy_arn(arn) for arn in attached_policy_arns
    ) or _has_admin_equivalent_statement(allow_statements):
        return "AdministratorAccess"
    if any(_is_power_user_policy_arn(arn) for arn in attached_policy_arns):
        return "PowerUserAccess"
    if _has_iam_write_statement(allow_statements):
        return "IAMWrite"
    if _has_sensitive_service_statement(allow_statements):
        return "SensitiveService"
    return "Other"
