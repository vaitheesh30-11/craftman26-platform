"""fetch_org_context -- phase-03 §4 Step 1: `DescribeOrganization`,
paginated `ListAccounts`, and a full OU tree via `ListRoots` ->
depth-first `ListOrganizationalUnitsForParent` with a visited-set.

Cached 15 min in DDB `SentinelPolicies` per the spec -- `OrgContextCache` is
a Protocol so the cache is an injection point: production wires
`adapters.ddb.policies.PoliciesCacheClient` (see docs/decisions/0023 §3),
tests pass `None` or a fixture double. Organizations calls go through the
caller-supplied `boto3.Session` directly (never a fresh `boto3.client()`
call) -- the same "boto3 only through adapters/, except the one documented
exception for read APIs `cross_account.assume()` itself names" pattern
`tools/f1/scan.py` established (`tools/common/cross_account.py`'s own
docstring: "every specialist tool that reads a member account's
IAM/Organizations/Access Analyzer/CloudTrail/Identity Center state goes
through assume()").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    import boto3
    from mypy_boto3_organizations.client import OrganizationsClient

# AWS Organizations caps OU nesting at 5 levels below the root; this bound is
# purely defensive against an unexpected cycle (Organizations does not
# document parent-cycles as possible, but a defensive depth cap costs
# nothing and prevents an infinite walk if that ever changes).
_MAX_OU_DEPTH = 25
_DEFAULT_CACHE_TTL_SECONDS = 900  # 15 min, per phase-03 §4 Step 1


@dataclass(frozen=True, slots=True)
class OrgContext:
    org_id: str
    master_account_id: str
    feature_set: str
    account_ids: list[str] = field(default_factory=list)
    ou_paths: list[str] = field(default_factory=list)


class OrgContextCache(Protocol):
    def get(self, org_id: str) -> OrgContext | None: ...
    def put(self, context: OrgContext, *, ttl_seconds: int) -> None: ...


def _list_all_accounts(client: OrganizationsClient) -> list[str]:
    account_ids: list[str] = []
    for page in client.get_paginator("list_accounts").paginate():
        account_ids.extend(account["Id"] for account in page["Accounts"])
    return account_ids


def _walk_ou_tree(client: OrganizationsClient, *, org_id: str, root_id: str) -> list[str]:
    paths: list[str] = []
    visited: set[str] = set()

    def _walk(parent_id: str, parent_path: str, depth: int) -> None:
        if parent_id in visited or depth > _MAX_OU_DEPTH:
            return
        visited.add(parent_id)
        paths.append(parent_path)
        for page in client.get_paginator("list_organizational_units_for_parent").paginate(
            ParentId=parent_id
        ):
            for ou in page["OrganizationalUnits"]:
                _walk(ou["Id"], f"{parent_path}{ou['Id']}/", depth + 1)

    _walk(root_id, f"{org_id}/{root_id}/", 0)
    return paths


def _list_all_ou_paths(client: OrganizationsClient, *, org_id: str) -> list[str]:
    paths: list[str] = []
    for root_page in client.get_paginator("list_roots").paginate():
        for root in root_page["Roots"]:
            paths.extend(_walk_ou_tree(client, org_id=org_id, root_id=root["Id"]))
    return paths


def fetch_org_context(
    session: boto3.Session,
    *,
    cache: OrgContextCache | None = None,
    cache_ttl_seconds: int = _DEFAULT_CACHE_TTL_SECONDS,
) -> OrgContext:
    client: OrganizationsClient = session.client("organizations")

    org = client.describe_organization()["Organization"]
    org_id = org["Id"]

    if cache is not None:
        cached = cache.get(org_id)
        if cached is not None:
            return cached

    context = OrgContext(
        org_id=org_id,
        master_account_id=org["MasterAccountId"],
        feature_set=org["FeatureSet"],
        account_ids=_list_all_accounts(client),
        ou_paths=_list_all_ou_paths(client, org_id=org_id),
    )

    if cache is not None:
        cache.put(context, ttl_seconds=cache_ttl_seconds)
    return context
