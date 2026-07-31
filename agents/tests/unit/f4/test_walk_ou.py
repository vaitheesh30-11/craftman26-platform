from __future__ import annotations

import json

import boto3
import pytest
from iam_sentinel_adapters.circuit_breaker import BreakerAccessor
from iam_sentinel_adapters.ddb.policies import PoliciesCacheClient
from moto import mock_aws

from iam_sentinel_agents.tools.f4 import walk_ou

pytestmark = pytest.mark.unit


def _setup_org() -> tuple[object, str, str, str, str]:
    org = boto3.client("organizations", region_name="us-east-1")
    org.create_organization(FeatureSet="ALL")
    org_id = org.describe_organization()["Organization"]["Id"]
    root_id = org.list_roots()["Roots"][0]["Id"]
    ou = org.create_organizational_unit(ParentId=root_id, Name="Prod")["OrganizationalUnit"]
    account_id = org.create_account(Email="a@b.com", AccountName="acct1")["CreateAccountStatus"][
        "AccountId"
    ]
    org.move_account(AccountId=account_id, SourceParentId=root_id, DestinationParentId=ou["Id"])

    scp = org.create_policy(
        Content=json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {"Effect": "Deny", "Action": "ec2:TerminateInstances", "Resource": "*"}
                ],
            }
        ),
        Description="root scp",
        Name="RootDeny",
        Type="SERVICE_CONTROL_POLICY",
    )["Policy"]["PolicySummary"]
    org.attach_policy(PolicyId=scp["Id"], TargetId=root_id)
    return org, org_id, root_id, ou["Id"], account_id


def _policies_table() -> object:
    ddb = boto3.resource("dynamodb", region_name="us-east-1")
    ddb.create_table(
        TableName="SentinelPolicies-test",
        KeySchema=[
            {"AttributeName": "org_id", "KeyType": "HASH"},
            {"AttributeName": "policy_arn", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "org_id", "AttributeType": "S"},
            {"AttributeName": "policy_arn", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    return ddb.Table("SentinelPolicies-test")


def _breaker() -> BreakerAccessor:
    ddb = boto3.resource("dynamodb", region_name="us-east-1")
    ddb.create_table(
        TableName="SentinelBreakers-test",
        KeySchema=[{"AttributeName": "breaker_name", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "breaker_name", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    return BreakerAccessor(table=ddb.Table("SentinelBreakers-test"))


@mock_aws
def test_walk_chain_orders_root_to_target_and_includes_attached_scps() -> None:
    org, org_id, root_id, ou_id, account_id = _setup_org()
    cache = PoliciesCacheClient(table=_policies_table(), breaker=_breaker())

    chain = walk_ou.walk_chain(account_id, org_client=org, org_id=org_id, policies_cache=cache)

    assert [level.level for level in chain] == ["root", "ou", "account"]
    assert chain[0].target == root_id
    assert chain[1].target == ou_id
    assert chain[2].target == account_id
    root_policy_names = {policy.name for policy in chain[0].policies}
    assert "FullAWSAccess" in root_policy_names
    assert "RootDeny" in root_policy_names
    # RootDeny is only attached at the root -- it must not also appear at
    # the OU or account level (each level's `policies` are locally attached
    # policies, not the accumulated effective set; that accumulation is
    # `evaluate_action`'s job, not `walk_chain`'s).
    assert "RootDeny" not in {policy.name for policy in chain[2].policies}


@mock_aws
def test_walk_chain_for_a_root_target_returns_a_single_level() -> None:
    org, org_id, root_id, _ou_id, _account_id = _setup_org()

    chain = walk_ou.walk_chain(root_id, org_client=org, org_id=org_id, policies_cache=None)

    assert len(chain) == 1
    assert chain[0].level == "root"


@mock_aws
def test_policies_cache_serves_a_second_walk_without_a_fresh_describe_policy_call() -> None:
    org, org_id, _root_id, _ou_id, account_id = _setup_org()
    cache = PoliciesCacheClient(table=_policies_table(), breaker=_breaker())

    first_chain = walk_ou.walk_chain(
        account_id, org_client=org, org_id=org_id, policies_cache=cache
    )
    root_deny_arn = next(
        policy.arn for policy in first_chain[0].policies if policy.name == "RootDeny"
    )

    cached = cache.get(org_id, root_deny_arn)
    assert cached is not None
    assert cached["name"] == "RootDeny"

    # A second walk must produce the identical chain shape using the cache.
    second_chain = walk_ou.walk_chain(
        account_id, org_client=org, org_id=org_id, policies_cache=cache
    )
    assert {p.name for p in second_chain[0].policies} == {p.name for p in first_chain[0].policies}
