"""`refresh_slr_db` (phase-09 §4 Step 2).

moto's IAM mock only returns policies actually created in the test (it
cannot fabricate real AWS-managed `Scope="AWS"` policies), so
`enumerate_live_actions` is exercised here against a customer-managed
policy moto reports as `Scope="Local"` -- that's enough to prove the real
mechanism (pagination, name filtering against the seed's `slr_name`
mapping, `GetPolicyVersion` parsing) independent of the `Scope` filter
value production hardcodes. See docs/decisions/0023.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import boto3
import pytest
from iam_sentinel_adapters.ddb.slrs import SlrsClient
from iam_sentinel_adapters.settings import settings as adapter_settings
from moto import mock_aws

from iam_sentinel_agents.tools.f8.refresh import enumerate_live_actions, refresh_slr_db

if TYPE_CHECKING:
    from mypy_boto3_iam.client import IAMClient

pytestmark = pytest.mark.unit

_REGION = "us-east-1"
_SEED = {
    "autoscaling.amazonaws.com": {
        "slr_name": "AWSServiceRoleForAutoScaling",
        "required_actions": ["ec2:DescribeInstances"],
        "optional_actions": [],
        "core_actions": ["ec2:DescribeInstances"],
        "source": "AWS Service Authorization Reference",
        "source_url": "https://docs.aws.amazon.com/service-authorization/latest/reference/list_autoscaling.html",
    }
}


def _create_slrs_table() -> None:
    ddb = boto3.resource("dynamodb", region_name=_REGION)
    ddb.create_table(
        TableName=adapter_settings.slrs_table,
        KeySchema=[{"AttributeName": "service_principal", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "service_principal", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    # DynamoDbHelper's default BreakerAccessor reads this table on every
    # call -- needs to exist under moto too (see test_scan_handler.py).
    ddb.create_table(
        TableName=adapter_settings.breakers_table,
        KeySchema=[{"AttributeName": "breaker_name", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "breaker_name", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )


@mock_aws
def test_enumerate_live_actions_merges_a_new_allow_action_from_iam() -> None:
    iam: IAMClient = boto3.client("iam", region_name=_REGION)
    iam.create_policy(
        PolicyName="AWSServiceRoleForAutoScaling",
        PolicyDocument=json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": ["ec2:DescribeInstances", "ec2:RunInstances"],
                        "Resource": "*",
                    }
                ],
            }
        ),
    )

    live = enumerate_live_actions(iam, _SEED, scope="Local")

    assert live["AWSServiceRoleForAutoScaling"] == ["ec2:DescribeInstances", "ec2:RunInstances"]


@mock_aws
def test_refresh_bumps_db_version_only_when_a_row_actually_changed() -> None:
    boto3.setup_default_session(region_name=_REGION)
    _create_slrs_table()
    iam: IAMClient = boto3.client("iam", region_name=_REGION)
    iam.create_policy(
        PolicyName="AWSServiceRoleForAutoScaling",
        PolicyDocument=json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [{"Effect": "Allow", "Action": "ec2:RunInstances", "Resource": "*"}],
            }
        ),
    )
    slrs_client = SlrsClient()

    first = refresh_slr_db(
        iam=iam, slrs_client=slrs_client, seed=_SEED, last_updated="2026-07-31", scope="Local"
    )
    assert first["changed"] is True
    assert first["db_version"] == "1"

    second = refresh_slr_db(
        iam=iam, slrs_client=slrs_client, seed=_SEED, last_updated="2026-08-07", scope="Local"
    )
    assert second["changed"] is False
    assert second["db_version"] == "1"
