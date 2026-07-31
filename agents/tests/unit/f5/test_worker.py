"""session_kill_worker (phase-06 §8 Test Plan: "verify the emitted inline
policy JSON matches the required shape exactly"; "token_issue_time_cutoff
is always in ISO8601 UTC with Z suffix"; "simulate a member-account IAM
API error; verify DLQ + SNS + no phantom TerminationRecord in DDB").
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, UTC
from unittest.mock import MagicMock, patch

import boto3
import pytest
from iam_sentinel_adapters.ddb.revocations import RevocationsClient
from moto import mock_aws

from iam_sentinel_agents.tools.f5 import worker
from tests.unit.f5 import _ddb

pytestmark = pytest.mark.unit

_ACCOUNT_ID = "123456789012"
_ROLE_ARN = f"arn:aws:iam::{_ACCOUNT_ID}:role/aws-reserved/sso.amazonaws.com/AWSReservedSSO_Ops_abc"
_ROLE_NAME = "AWSReservedSSO_Ops_abc"
_POLICY_NAME = "SENTINEL_EMERGENCY_REVOKE_1730000000"


@mock_aws
def test_worker_attaches_the_exact_deny_policy_shape_with_z_suffix_cutoff() -> None:
    iam = boto3.client("iam", region_name="us-east-1")
    iam.create_role(
        RoleName=_ROLE_NAME,
        Path="/aws-reserved/sso.amazonaws.com/",
        AssumeRolePolicyDocument='{"Version":"2012-10-17","Statement":[]}',
    )
    table = _ddb.revocations_table()
    breaker = _ddb.breaker()
    session = boto3.Session(region_name="us-east-1")

    cutoff = datetime(2026, 7, 31, 12, 0, 0, tzinfo=UTC)
    ttl_expires = cutoff + timedelta(hours=1)

    record = worker.process_kill_message(
        account_id=_ACCOUNT_ID,
        role_arn=_ROLE_ARN,
        token_issue_time_cutoff=cutoff,
        ttl_expires_at=ttl_expires,
        revocation_policy_name=_POLICY_NAME,
        correlation_id="01JBP2VHF9K3Q0Z8R7X6M5N4A6",
        session=session,
        revocations_client=RevocationsClient(table=table, breaker=breaker),
        evidence_client=MagicMock(),
        security_hub_client=MagicMock(),
        sns_client=MagicMock(),
        sleep_fn=lambda _seconds: None,
    )

    attached = iam.get_role_policy(RoleName=_ROLE_NAME, PolicyName=_POLICY_NAME)
    document = (
        json.loads(attached["PolicyDocument"])
        if isinstance(attached["PolicyDocument"], str)
        else attached["PolicyDocument"]
    )

    assert document == {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Deny",
                "Action": "*",
                "Resource": "*",
                "Condition": {"DateLessThan": {"aws:TokenIssueTime": "2026-07-31T12:00:00Z"}},
            }
        ],
    }
    assert record.verified_attached is True
    assert record.token_issue_time_cutoff.isoformat().endswith(("Z", "+00:00"))

    stored = RevocationsClient(table=table, breaker=breaker).get(_ACCOUNT_ID, _ROLE_ARN)
    assert stored is not None
    assert stored["verified_attached"] is True


@mock_aws
def test_worker_iam_failure_writes_no_ddb_record_and_notifies_sns() -> None:
    table = _ddb.revocations_table()
    breaker = _ddb.breaker()
    session = boto3.Session(region_name="us-east-1")
    sns_mock = MagicMock()

    with patch.object(session, "client") as fake_client_factory:
        broken_iam = MagicMock()
        broken_iam.exceptions.NoSuchEntityException = Exception
        broken_iam.put_role_policy.side_effect = RuntimeError(
            "AccessDenied: simulated member-account failure"
        )
        fake_client_factory.return_value = broken_iam

        with pytest.raises(worker.WorkerFailureError):
            worker.process_kill_message(
                account_id=_ACCOUNT_ID,
                role_arn=_ROLE_ARN,
                token_issue_time_cutoff=datetime.now(UTC),
                ttl_expires_at=datetime.now(UTC) + timedelta(hours=1),
                revocation_policy_name=_POLICY_NAME,
                correlation_id="01JBP2VHF9K3Q0Z8R7X6M5N4A7",
                session=session,
                revocations_client=RevocationsClient(table=table, breaker=breaker),
                sns_client=sns_mock,
                sleep_fn=lambda _seconds: None,
            )

    assert RevocationsClient(table=table, breaker=breaker).get(_ACCOUNT_ID, _ROLE_ARN) is None
    sns_mock.publish_critical_finding.assert_called_once()
