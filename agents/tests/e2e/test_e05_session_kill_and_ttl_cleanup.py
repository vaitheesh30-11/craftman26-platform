"""E-05 — GuardDuty-triggered SSO session kill (phase-13 scenario table).
Real `tools/f5/dispatch.dispatch` fan-out (SQS FIFO + `RevocationsClient`)
and real `tools/f5/cleanup.run_cleanup` TTL sweep, against moto SQS/DDB and
the same fake SSO-admin client `tests/unit/f5/test_dispatch.py` already
establishes as this module's precedent (no moto SSO Admin support).
Passes when: 3 accounts, 3 Deny policies attached (revocation records)
in under 30s (real wall-clock, well within budget for an in-process moto
call), TTL cleanup verified.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, UTC
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import boto3
from iam_sentinel_adapters.sns.client import SnsClient
from iam_sentinel_adapters.sqs.client import SqsClient

from iam_sentinel_agents.tools.common import cross_account
from iam_sentinel_agents.tools.f5 import cleanup, dispatch

if TYPE_CHECKING:
    from iam_sentinel_adapters.ddb.revocations import RevocationsClient

_ACCOUNTS = ("111111111111", "222222222222", "333333333333")
_PERMISSION_SET_ARN = "arn:aws:sso:::permissionSet/ssoins-1234/ps-5678"
_PERMISSION_SET_NAME = "EmergencyOps"
_INSTANCE_ARN = "arn:aws:sso:::instance/ssoins-1234"


def _fake_sso_client() -> MagicMock:
    sso = MagicMock()
    sso.list_instances.return_value = {"Instances": [{"InstanceArn": _INSTANCE_ARN}]}
    sso.describe_permission_set.return_value = {"PermissionSet": {"Name": _PERMISSION_SET_NAME}}
    accounts_paginator = MagicMock()
    accounts_paginator.paginate.return_value = [{"AccountIds": list(_ACCOUNTS)}]
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


def test_e05_guardduty_triggered_kill_hits_three_accounts_under_30s(
    revocations_client: RevocationsClient,
) -> None:
    sqs = boto3.client("sqs", region_name="us-east-1")
    queue_url = sqs.create_queue(
        QueueName="SessionKillQueue.fifo",
        Attributes={"FifoQueue": "true", "ContentBasedDeduplication": "false"},
    )["QueueUrl"]
    _provision_sso_role(_ACCOUNTS[0])
    session = boto3.Session(region_name="us-east-1")

    start = time.monotonic()
    with patch.object(cross_account, "assume", return_value=session):
        payload = dispatch.dispatch(
            permission_set_arn=_PERMISSION_SET_ARN,
            principal_arn=None,
            ttl_seconds=900,
            reason="GuardDuty finding: anomalous console login",
            trigger_source="guardduty",
            correlation_id="01JBP2VHF9K3Q0Z8R7X6M5N4A6",
            sso_client=_fake_sso_client(),
            sqs_client=SqsClient(queue_url=queue_url, client=sqs),
            revocations_client=revocations_client,
            denylist_patterns=[],
        )
    elapsed = time.monotonic() - start

    assert elapsed < 30.0
    assert payload.accounts_targeted == 3
    assert len(payload.terminations) == 3
    assert {t.account_id for t in payload.terminations} == set(_ACCOUNTS)
    assert payload.accounts_failed == []

    for termination in payload.terminations:
        stored = revocations_client.get(termination.account_id, termination.role_arn)
        assert stored is not None
        assert stored["cleaned"] is False

    # TTL cleanup: fast-forward past expiry and run the real sweep.
    future = datetime.now(UTC) + timedelta(seconds=901)
    fake_iam = MagicMock()
    fake_iam.exceptions.NoSuchEntityException = type("NoSuchEntityException", (Exception,), {})
    fake_iam.get_role_policy.side_effect = fake_iam.exceptions.NoSuchEntityException()
    fake_session = MagicMock()
    fake_session.client.return_value = fake_iam

    cleanup_result = cleanup.run_cleanup(
        now=future,
        revocations_client=revocations_client,
        sns_client=SnsClient(
            topic_arn=boto3.client("sns", region_name="us-east-1").create_topic(
                Name="F5CleanupTopic"
            )["TopicArn"],
            client=boto3.client("sns", region_name="us-east-1"),
        ),
        cross_account_assume=lambda *a, **k: fake_session,
    )

    assert set(cleanup_result["cleaned"]) == {t.role_arn for t in payload.terminations}
    for termination in payload.terminations:
        stored = revocations_client.get(termination.account_id, termination.role_arn)
        assert stored is not None
        assert stored["cleaned"] is True
