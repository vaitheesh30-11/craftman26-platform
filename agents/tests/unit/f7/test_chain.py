"""`tools/f7/chain.walk_scp_chain` against moto's Organizations mock."""

from __future__ import annotations

import boto3
import pytest
from moto import mock_aws

from iam_sentinel_agents.tools.f7 import chain
from tests.unit.f7._org_provision import provision_classic_collision

pytestmark = pytest.mark.unit


@mock_aws
def test_walks_root_to_account_in_order() -> None:
    org = boto3.client("organizations", region_name="us-east-1")
    account_id = provision_classic_collision(org)

    levels = chain.walk_scp_chain(account_id, organizations_client=org)

    assert [level.level for level in levels] == ["root", "ou", "account"]
    assert levels[-1].target_id == account_id


@mock_aws
def test_each_level_resolves_its_attached_policy_documents() -> None:
    org = boto3.client("organizations", region_name="us-east-1")
    account_id = provision_classic_collision(org)

    levels = chain.walk_scp_chain(account_id, organizations_client=org)

    root_names = {policy.name for policy in levels[0].policies}
    ou_names = {policy.name for policy in levels[1].policies}
    assert "RootDenyRunInstances" in root_names
    assert "OuAllowRunInstances" in ou_names
    for level in levels:
        for policy in level.policies:
            assert "Statement" in policy.document
