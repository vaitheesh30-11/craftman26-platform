"""SSO Admin discovery (phase-06 §4 Step 2): resolve a permission-set ARN
into the accounts it's assigned to and the `(principal_type, principal_id)`
pairs on each, plus the permission-set's short name, from the delegated-
admin Identity Center account.

Deliberate deviation from §4 Step 2's own pseudocode -- "ListAccountAssignments
(InstanceArn, PermissionSetArn)" paginated, with no `AccountId` -- because
the real API has no such call shape: `sso-admin:ListAccountAssignments`
is scoped to one account per call (`InstanceArn` + `AccountId` +
`PermissionSetArn`) and does not enumerate accounts on its own. The account
list must come from `sso-admin:ListAccountsForProvisionedPermissionSet`
first; `list_assignments` below does that fan-out internally so callers
still get one flat list of assignments as the spec's pseudocode implies.
See docs/decisions/0023.

Calls `sso-admin` boto3 read APIs directly rather than through an
adapters/ client -- the same deliberate exception F1's `tools/f1/scan.py`
documents for cross-account IAM reads (agents/README.md §1): no
`adapters/` package wraps Identity Center APIs, and these are read-only,
central-account calls (not the cross-account IAM writes that make F5
security-sensitive).
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from mypy_boto3_sso_admin.client import SSOAdminClient


class DiscoveryError(RuntimeError):
    """Raised when no Identity Center instance is reachable."""


def resolve_instance_arn(sso_client: SSOAdminClient) -> str:
    instances = sso_client.list_instances()["Instances"]
    if not instances:
        raise DiscoveryError("no IAM Identity Center instance is reachable")
    return str(instances[0]["InstanceArn"])


def describe_permission_set_name(
    sso_client: SSOAdminClient, *, instance_arn: str, permission_set_arn: str
) -> str:
    described = sso_client.describe_permission_set(
        InstanceArn=instance_arn, PermissionSetArn=permission_set_arn
    )
    return str(described["PermissionSet"]["Name"])


def _accounts_for_permission_set(
    sso_client: SSOAdminClient, *, instance_arn: str, permission_set_arn: str
) -> list[str]:
    account_ids: list[str] = []
    for page in sso_client.get_paginator("list_accounts_for_provisioned_permission_set").paginate(
        InstanceArn=instance_arn, PermissionSetArn=permission_set_arn
    ):
        account_ids.extend(page["AccountIds"])
    return account_ids


def list_assignments(
    sso_client: SSOAdminClient,
    *,
    instance_arn: str,
    permission_set_arn: str,
    principal_arn: str | None = None,
) -> list[dict[str, Any]]:
    """Returns every `{AccountId, PrincipalType, PrincipalId}` assignment
    across every account the permission set is provisioned to.

    `principal_arn` filtering: `ListAccountAssignments` returns Identity
    Store `PrincipalId`s, not ARNs -- resolving an ARN to a PrincipalId
    needs `identitystore:DescribeUser`/`DescribeGroup`, which §7's IAM
    policy for this Lambda role does not grant. Per docs/decisions/0023,
    filtering here only matches when the caller already passes a bare
    PrincipalId (the last path segment of `principal_arn`); true ARN
    resolution is deferred.
    """
    assignments: list[dict[str, Any]] = []
    for account_id in _accounts_for_permission_set(
        sso_client, instance_arn=instance_arn, permission_set_arn=permission_set_arn
    ):
        for page in sso_client.get_paginator("list_account_assignments").paginate(
            InstanceArn=instance_arn, AccountId=account_id, PermissionSetArn=permission_set_arn
        ):
            for assignment in page["AccountAssignments"]:
                assignments.append({**assignment, "AccountId": account_id})

    if principal_arn is None:
        return assignments
    candidate_id = principal_arn.rsplit("/", 1)[-1]
    return [a for a in assignments if a["PrincipalId"] == candidate_id]
