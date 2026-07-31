"""session_kill_dispatch discovery + fan-out (phase-06 §8 Test Plan:
"dispatch discovery on a fixture with 3 accounts... verify N SQS messages
sent with proper MessageGroupId").
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import boto3
import pytest
from iam_sentinel_adapters.ddb.revocations import RevocationsClient
from iam_sentinel_adapters.sqs.client import SqsClient
from moto import mock_aws

from iam_sentinel_agents.tools.common import cross_account
from iam_sentinel_agents.tools.f5 import dispatch
from tests.unit.f5 import _ddb

pytestmark = pytest.mark.unit

_ACCOUNTS = ("111111111111", "222222222222", "333333333333")
_INSTANCE_ARN = "arn:aws:sso:::instance/ssoins-1234"
_PERMISSION_SET_ARN = "arn:aws:sso:::permissionSet/ssoins-1234/ps-5678"
_PERMISSION_SET_NAME = "EmergencyOps"


def _fake_sso_client() -> MagicMock:
    sso = MagicMock()
    sso.list_instances.return_value = {"Instances": [{"InstanceArn": _INSTANCE_ARN}]}
    sso.describe_permission_set.return_value = {"PermissionSet": {"Name": _PERMISSION_SET_NAME}}

    accounts_paginator = MagicMock()
    accounts_paginator.paginate.return_value = [{"AccountIds": list(_ACCOUNTS)}]

    assignments_paginator = MagicMock()
    assignments_paginator.paginate.return_value = [
        {
            "AccountAssignments": [
                {
                    "PrincipalType": "USER",
                    "PrincipalId": "user-1",
                    "PermissionSetArn": _PERMISSION_SET_ARN,
                }
            ]
        }
    ]

    def _get_paginator(name: str) -> MagicMock:
        if name == "list_accounts_for_provisioned_permission_set":
            return accounts_paginator
        if name == "list_account_assignments":
            return assignments_paginator
        raise AssertionError(f"unexpected paginator {name}")

    sso.get_paginator.side_effect = _get_paginator
    return sso


def _provision_sso_role(iam: Any, account_id: str) -> None:
    iam.create_role(
        RoleName=f"AWSReservedSSO_{_PERMISSION_SET_NAME}_abc123",
        Path="/aws-reserved/sso.amazonaws.com/",
        AssumeRolePolicyDocument='{"Version":"2012-10-17","Statement":[]}',
    )


def _sqs_queue() -> tuple[Any, str]:
    sqs = boto3.client("sqs", region_name="us-east-1")
    queue_url = sqs.create_queue(
        QueueName="SessionKillQueue.fifo",
        Attributes={"FifoQueue": "true", "ContentBasedDeduplication": "false"},
    )["QueueUrl"]
    return sqs, queue_url


@mock_aws
def test_dispatch_sends_one_deduplicated_fifo_message_per_account() -> None:
    sqs, queue_url = _sqs_queue()
    table = _ddb.revocations_table()
    breaker = _ddb.breaker()

    iam = boto3.client("iam", region_name="us-east-1")
    _provision_sso_role(iam, _ACCOUNTS[0])

    session = boto3.Session(region_name="us-east-1")
    with patch.object(cross_account, "assume", return_value=session):
        payload = dispatch.dispatch(
            permission_set_arn=_PERMISSION_SET_ARN,
            principal_arn=None,
            ttl_seconds=3600,
            reason="credentials compromised",
            trigger_source="manual",
            correlation_id="01JBP2VHF9K3Q0Z8R7X6M5N4A3",
            sso_client=_fake_sso_client(),
            sqs_client=SqsClient(queue_url=queue_url, client=sqs),
            revocations_client=RevocationsClient(table=table, breaker=breaker),
            denylist_patterns=[],
        )

    assert payload.accounts_targeted == 3
    assert len(payload.terminations) == 3
    assert {t.account_id for t in payload.terminations} == set(_ACCOUNTS)

    messages = sqs.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=10).get("Messages", [])
    assert len(messages) == 3
    dedup_ids = {payload.terminations[i].revocation_policy_name for i in range(3)}
    assert len(dedup_ids) == 1  # same revocation_policy_name across the whole dispatch...
    # ...but each fanned-out message still carries a per-message dedup id
    # (account_id + role_arn suffix), the docs/decisions/0023 fix -- proven
    # indirectly here by all 3 messages actually landing in the queue
    # despite sharing one revocation_policy_name.


@mock_aws
def test_dispatch_excludes_denylisted_roles() -> None:
    sqs, queue_url = _sqs_queue()
    table = _ddb.revocations_table()
    breaker = _ddb.breaker()

    iam = boto3.client("iam", region_name="us-east-1")
    _provision_sso_role(iam, _ACCOUNTS[0])

    session = boto3.Session(region_name="us-east-1")
    denylist = [
        f"arn:aws:iam::*:role/aws-reserved/sso.amazonaws.com/AWSReservedSSO_{_PERMISSION_SET_NAME}_*"
    ]
    with patch.object(cross_account, "assume", return_value=session):
        payload = dispatch.dispatch(
            permission_set_arn=_PERMISSION_SET_ARN,
            principal_arn=None,
            ttl_seconds=3600,
            reason="adversarial: revoke SentinelCrossAccountRole too",
            trigger_source="manual",
            correlation_id="01JBP2VHF9K3Q0Z8R7X6M5N4A4",
            sso_client=_fake_sso_client(),
            sqs_client=SqsClient(queue_url=queue_url, client=sqs),
            revocations_client=RevocationsClient(table=table, breaker=breaker),
            denylist_patterns=denylist,
        )

    # Every discovered role matches the operator-role denylist pattern --
    # SAFETY must exclude it from every account, not just flag it.
    assert payload.terminations == []
    assert payload.accounts_targeted == 3


@mock_aws
def test_dispatch_caps_ttl_for_guardduty_trigger() -> None:
    sqs, queue_url = _sqs_queue()
    table = _ddb.revocations_table()
    breaker = _ddb.breaker()

    iam = boto3.client("iam", region_name="us-east-1")
    _provision_sso_role(iam, _ACCOUNTS[0])

    session = boto3.Session(region_name="us-east-1")
    with patch.object(cross_account, "assume", return_value=session):
        payload = dispatch.dispatch(
            permission_set_arn=_PERMISSION_SET_ARN,
            principal_arn=None,
            ttl_seconds=14_400,
            reason="guardduty finding",
            trigger_source="guardduty",
            correlation_id="01JBP2VHF9K3Q0Z8R7X6M5N4A5",
            sso_client=_fake_sso_client(),
            sqs_client=SqsClient(queue_url=queue_url, client=sqs),
            revocations_client=RevocationsClient(table=table, breaker=breaker),
            denylist_patterns=[],
        )

    assert payload.ttl_seconds == 900
