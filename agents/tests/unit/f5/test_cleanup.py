"""session_kill_cleanup (phase-06 §8 Test Plan: "verify the 'new revocation
before cleanup' branch extends TTL instead of deleting").
"""

from __future__ import annotations

from datetime import datetime, timedelta, UTC
from typing import Any
from unittest.mock import MagicMock

import boto3
import pytest
from iam_sentinel_adapters.ddb.revocations import RevocationsClient
from moto import mock_aws

from iam_sentinel_agents.tools.f5 import cleanup
from tests.unit.f5 import _ddb

pytestmark = pytest.mark.unit

_ACCOUNT_ID = "123456789012"
_ROLE_ARN = f"arn:aws:iam::{_ACCOUNT_ID}:role/aws-reserved/sso.amazonaws.com/AWSReservedSSO_Ops_abc"
_ROLE_NAME = "AWSReservedSSO_Ops_abc"


@mock_aws
def test_cleanup_deletes_the_expired_inline_policy_and_marks_cleaned() -> None:
    iam = boto3.client("iam", region_name="us-east-1")
    iam.create_role(
        RoleName=_ROLE_NAME,
        Path="/aws-reserved/sso.amazonaws.com/",
        AssumeRolePolicyDocument='{"Version":"2012-10-17","Statement":[]}',
    )
    iam.put_role_policy(
        RoleName=_ROLE_NAME,
        PolicyName="SENTINEL_EMERGENCY_REVOKE_1000",
        PolicyDocument=(
            '{"Version":"2012-10-17","Statement":[{"Effect":"Deny","Action":"*","Resource":"*"}]}'
        ),
    )

    table = _ddb.revocations_table()
    breaker = _ddb.breaker()
    revocations = RevocationsClient(table=table, breaker=breaker)
    now = datetime.now(UTC)
    revocations.put(
        {
            "account_id": _ACCOUNT_ID,
            "role_arn": _ROLE_ARN,
            "revocation_policy_name": "SENTINEL_EMERGENCY_REVOKE_1000",
            "token_issue_time_cutoff": (now - timedelta(hours=1)).isoformat(),
            "attached_at": (now - timedelta(hours=1)).isoformat(),
            "ttl_expires_at": (now - timedelta(minutes=1)).isoformat(),
            "verify_attempts": 1,
            "verified_attached": True,
            "correlation_id": "01JBP2VHF9K3Q0Z8R7X6M5N4A8",
            "cleaned": False,
        }
    )

    session = boto3.Session(region_name="us-east-1")
    result = cleanup.run_cleanup(
        now=now,
        revocations_client=revocations,
        sns_client=MagicMock(),
        cross_account_assume=lambda *_a, **_k: session,
    )

    assert result["cleaned"] == [_ROLE_ARN]
    stored = revocations.get(_ACCOUNT_ID, _ROLE_ARN)
    assert stored is not None
    assert stored["cleaned"] is True
    with pytest.raises(iam.exceptions.NoSuchEntityException):
        iam.get_role_policy(RoleName=_ROLE_NAME, PolicyName="SENTINEL_EMERGENCY_REVOKE_1000")


@mock_aws
def test_cleanup_extends_instead_of_deleting_when_a_newer_revocation_is_live() -> None:
    table = _ddb.revocations_table()
    breaker = _ddb.breaker()
    now = datetime.now(UTC)

    stale_snapshot = {
        "account_id": _ACCOUNT_ID,
        "role_arn": _ROLE_ARN,
        "revocation_policy_name": "SENTINEL_EMERGENCY_REVOKE_1000",
        "ttl_expires_at": (now - timedelta(minutes=1)).isoformat(),
        "verified_attached": True,
        "cleaned": False,
        "correlation_id": "01JBP2VHF9K3Q0Z8R7X6M5N4A9",
    }

    class _FakeQueryExpired(RevocationsClient):
        def query_expired(self, _now: datetime, *, limit: int = 100) -> list[dict[str, Any]]:
            return [stale_snapshot]

    fake_client = _FakeQueryExpired(table=table, breaker=breaker)
    # A newer dispatch already overwrote the live DDB item with a later
    # ttl_expires_at and a different revocation_policy_name before cleanup
    # re-reads it -- this is the extend-not-delete race from §4 Step 4.
    fake_client.put(
        {
            **stale_snapshot,
            "revocation_policy_name": "SENTINEL_EMERGENCY_REVOKE_2000",
            "ttl_expires_at": (now + timedelta(hours=1)).isoformat(),
        }
    )

    result = cleanup.run_cleanup(
        now=now,
        revocations_client=fake_client,
        sns_client=MagicMock(),
        cross_account_assume=MagicMock(
            side_effect=AssertionError("must not assume for an extended record")
        ),
    )

    assert result["extended"] == [_ROLE_ARN]
    assert result["cleaned"] == []
