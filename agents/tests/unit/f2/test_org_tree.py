"""tools/f2/org_tree.py -- phase-03 §4 Step 1: DescribeOrganization,
paginated ListAccounts, and a depth-first OU tree walk. §8 Test Plan:
"OU tree: fixture with 3 levels of OUs; verify traversal completeness."
"""

from __future__ import annotations

import boto3
import pytest
from moto import mock_aws

from iam_sentinel_agents.tools.f2.org_tree import fetch_org_context, OrgContext

pytestmark = pytest.mark.unit


@mock_aws
def test_fetch_org_context_walks_a_three_level_ou_tree() -> None:
    client = boto3.client("organizations", region_name="us-east-1")
    org = client.create_organization(FeatureSet="ALL")["Organization"]
    org_id = org["Id"]
    root_id = client.list_roots()["Roots"][0]["Id"]

    level1 = client.create_organizational_unit(ParentId=root_id, Name="Level1")[
        "OrganizationalUnit"
    ]["Id"]
    level2 = client.create_organizational_unit(ParentId=level1, Name="Level2")[
        "OrganizationalUnit"
    ]["Id"]
    client.create_organizational_unit(ParentId=level2, Name="Level3")

    session = boto3.Session(region_name="us-east-1")
    context = fetch_org_context(session)

    assert isinstance(context, OrgContext)
    assert context.org_id == org_id
    # root + level1 + level2 + level3 == 4 distinct OU-tree path entries.
    assert len(context.ou_paths) == 4
    assert all(path.startswith(f"{org_id}/{root_id}/") for path in context.ou_paths)
    assert any(path.endswith(f"{level1}/") for path in context.ou_paths)
    assert any(path.endswith(f"{level2}/") for path in context.ou_paths)


@mock_aws
def test_fetch_org_context_lists_all_accounts() -> None:
    client = boto3.client("organizations", region_name="us-east-1")
    client.create_organization(FeatureSet="ALL")
    client.create_account(AccountName="member-one", Email="member-one@example.com")
    client.create_account(AccountName="member-two", Email="member-two@example.com")

    session = boto3.Session(region_name="us-east-1")
    context = fetch_org_context(session)

    # Management account + the two created member accounts.
    assert len(context.account_ids) == 3


@mock_aws
def test_fetch_org_context_uses_cache_when_present() -> None:
    client = boto3.client("organizations", region_name="us-east-1")
    org = client.create_organization(FeatureSet="ALL")["Organization"]

    cached_context = OrgContext(
        org_id=org["Id"],
        master_account_id=org["MasterAccountId"],
        feature_set=org["FeatureSet"],
        account_ids=["999999999999"],
        ou_paths=["cached/path/"],
    )

    class _FakeCache:
        def get(self, org_id: str) -> OrgContext | None:
            assert org_id == org["Id"]
            return cached_context

        def put(self, context: OrgContext, *, ttl_seconds: int) -> None:
            raise AssertionError("put() should never be called on a cache hit")

    session = boto3.Session(region_name="us-east-1")
    result = fetch_org_context(session, cache=_FakeCache())

    assert result is cached_context


@mock_aws
def test_fetch_org_context_populates_cache_on_miss() -> None:
    client = boto3.client("organizations", region_name="us-east-1")
    client.create_organization(FeatureSet="ALL")

    puts: list[OrgContext] = []

    class _RecordingCache:
        def get(self, org_id: str) -> OrgContext | None:
            return None

        def put(self, context: OrgContext, *, ttl_seconds: int) -> None:
            assert ttl_seconds == 900
            puts.append(context)

    session = boto3.Session(region_name="us-east-1")
    fetch_org_context(session, cache=_RecordingCache())

    assert len(puts) == 1
