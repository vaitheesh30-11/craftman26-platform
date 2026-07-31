"""phase-13 §4 Step 6 — Cross-account fault-injection: a target account is
missing the Sentinel cross-account role. Real `tools/f5/dispatch.dispatch`
fan-out; `cross_account.assume` is patched to raise for exactly one of
three target accounts (the actual failure mode -- an un-onboarded account
-- not a network fault, so this is a distinct scenario from
`tests/chaos/`, which injects transport/service faults). Passes when: F5
dispatch emits a partial-success payload with `accounts_failed=[...]`,
and the two reachable accounts still complete.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import boto3
from iam_sentinel_adapters.errors import AccessDeniedError
from iam_sentinel_adapters.sqs.client import SqsClient

from iam_sentinel_agents.tools.common import cross_account
from iam_sentinel_agents.tools.f5 import dispatch

if TYPE_CHECKING:
    from iam_sentinel_adapters.ddb.revocations import RevocationsClient

_REACHABLE_ACCOUNTS = ("111111111111", "222222222222")
_UNREACHABLE_ACCOUNT = "999999999999"
_ALL_ACCOUNTS = (*_REACHABLE_ACCOUNTS, _UNREACHABLE_ACCOUNT)
_PERMISSION_SET_ARN = "arn:aws:sso:::permissionSet/ssoins-1234/ps-5678"
_PERMISSION_SET_NAME = "EmergencyOps"


def _fake_sso_client() -> MagicMock:
    sso = MagicMock()
    sso.list_instances.return_value = {"Instances": [{"InstanceArn": "arn:aws:sso:::instance/ssoins-1234"}]}
    sso.describe_permission_set.return_value = {"PermissionSet": {"Name": _PERMISSION_SET_NAME}}
    accounts_paginator = MagicMock()
    accounts_paginator.paginate.return_value = [{"AccountIds": list(_ALL_ACCOUNTS)}]
    assignments_paginator = MagicMock()
    assignments_paginator.paginate.return_value = [
        {"AccountAssignments": [{"PrincipalType": "USER", "PrincipalId": "u-1", "PermissionSetArn": _PERMISSION_SET_ARN}]}
    ]

    def _get_paginator(name: str) -> MagicMock:
        return {
            "list_accounts_for_provisioned_permission_set": accounts_paginator,
            "list_account_assignments": assignments_paginator,
        }[name]

    sso.get_paginator.side_effect = _get_paginator
    return sso


def _provision_sso_role(account_id: str) -> None:
    iam = boto3.client("iam", region_name="us-east-1")
    iam.create_role(
        RoleName=f"AWSReservedSSO_{_PERMISSION_SET_NAME}_abc123",
        Path="/aws-reserved/sso.amazonaws.com/",
        AssumeRolePolicyDocument='{"Version":"2012-10-17","Statement":[]}',
    )


def test_missing_cross_account_role_yields_partial_success(
    revocations_client: RevocationsClient,
) -> None:
    sqs = boto3.client("sqs", region_name="us-east-1")
    queue_url = sqs.create_queue(
        QueueName="SessionKillQueue.fifo",
        Attributes={"FifoQueue": "true", "ContentBasedDeduplication": "false"},
    )["QueueUrl"]
    _provision_sso_role(_REACHABLE_ACCOUNTS[0])

    reachable_session = boto3.Session(region_name="us-east-1")

    def _fake_assume(account_id: str, **_kwargs: object) -> boto3.Session:
        if account_id == _UNREACHABLE_ACCOUNT:
            raise AccessDeniedError(
                f"SentinelCrossAccountRole not found in account {account_id!r}"
            )
        return reachable_session

    original_assume = cross_account.assume
    cross_account.assume = _fake_assume  # type: ignore[assignment]
    try:
        payload = dispatch.dispatch(
            permission_set_arn=_PERMISSION_SET_ARN,
            principal_arn=None,
            ttl_seconds=3600,
            reason="credentials compromised",
            trigger_source="manual",
            correlation_id="01JBP2VHF9K3Q0Z8R7X6M5N4A7",
            sso_client=_fake_sso_client(),
            sqs_client=SqsClient(queue_url=queue_url, client=sqs),
            revocations_client=revocations_client,
            denylist_patterns=[],
        )
    finally:
        cross_account.assume = original_assume  # type: ignore[assignment]

    assert payload.accounts_targeted == 3
    assert payload.accounts_failed == [_UNREACHABLE_ACCOUNT]
    assert {t.account_id for t in payload.terminations} == set(_REACHABLE_ACCOUNTS)
    # The fan-out for the two reachable accounts completed despite one
    # account's discovery failing -- conservative, not fail-closed-on-all.
    assert len(payload.terminations) == len(_REACHABLE_ACCOUNTS)
