"""cross_account.assume() — caching, retry, and fail-fast behavior."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import patch

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from iam_sentinel_agents.errors import CrossAccountAssumeError
from iam_sentinel_agents.tools.common import cross_account

pytestmark = pytest.mark.unit

# moto's default mocked account — boto3 calls with moto's fake credentials
# resolve into this account, so `cross_account.assume`'s constructed ARN
# must target it for the mocked role to actually be found.
ACCOUNT_ID = "123456789012"
ROLE_NAME = "SentinelCrossAccountRole"


@pytest.fixture(autouse=True)
def _reset_cache() -> None:
    cross_account.clear_cache_for_tests()
    yield
    cross_account.clear_cache_for_tests()


@mock_aws
def test_assume_returns_a_working_session() -> None:
    _create_assumable_role()

    session = cross_account.assume(
        ACCOUNT_ID, feature_id="F1", correlation_id="01JBP2VHF9K3Q0Z8R7X6M5N4A3"
    )

    credentials = session.get_credentials()
    assert credentials is not None
    assert credentials.access_key is not None


@mock_aws
def test_assume_caches_credentials_across_calls() -> None:
    _create_assumable_role()

    with patch.object(
        cross_account, "_assume_role_once", wraps=cross_account._assume_role_once
    ) as spy:
        cross_account.assume(ACCOUNT_ID, feature_id="F1", correlation_id="01JBP2VHF9K3Q0Z8R7X6M5N4A3")
        cross_account.assume(ACCOUNT_ID, feature_id="F1", correlation_id="01JBP2VHF9K3Q0Z8R7X6M5N4A4")

    assert spy.call_count == 1


@mock_aws
def test_assume_refreshes_when_cache_within_safety_margin() -> None:
    _create_assumable_role()

    near_expiry = cross_account._CachedCredentials(
        access_key_id="stale-key",
        secret_access_key="stale-secret",
        session_token="stale-token",
        expiration=datetime.now(timezone.utc) + timedelta(minutes=2),
    )
    cross_account._CACHE.put(ACCOUNT_ID, ROLE_NAME, near_expiry)

    session = cross_account.assume(
        ACCOUNT_ID, feature_id="F1", correlation_id="01JBP2VHF9K3Q0Z8R7X6M5N4A3"
    )

    credentials = session.get_credentials()
    assert credentials is not None
    assert credentials.access_key != "stale-key"


def test_invalid_account_id_rejected() -> None:
    with pytest.raises(ValueError, match="12-digit"):
        cross_account.assume(
            "not-an-account", feature_id="F1", correlation_id="01JBP2VHF9K3Q0Z8R7X6M5N4A3"
        )


def test_access_denied_is_never_retried() -> None:
    error = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "nope"}}, "AssumeRole"
    )
    with (
        patch.object(cross_account, "_assume_role_once", side_effect=error),
        patch.object(cross_account.time, "sleep") as sleep_spy,
        pytest.raises(CrossAccountAssumeError, match="failed to assume"),
    ):
        cross_account.assume(
            ACCOUNT_ID, feature_id="F1", correlation_id="01JBP2VHF9K3Q0Z8R7X6M5N4A3"
        )
    sleep_spy.assert_not_called()


def test_throttling_is_retried_then_raises_after_exhaustion() -> None:
    error = ClientError(
        {"Error": {"Code": "ThrottlingException", "Message": "slow down"}}, "AssumeRole"
    )
    with (
        patch.object(cross_account, "_assume_role_once", side_effect=error) as assume_spy,
        patch.object(cross_account.time, "sleep") as sleep_spy,
        pytest.raises(CrossAccountAssumeError),
    ):
        cross_account.assume(
            ACCOUNT_ID, feature_id="F1", correlation_id="01JBP2VHF9K3Q0Z8R7X6M5N4A3"
        )
    assert assume_spy.call_count == 4  # initial + 3 retries
    assert sleep_spy.call_count == 3
    assert [call.args[0] for call in sleep_spy.call_args_list] == [0.2, 0.5, 2.0]


def test_throttling_recovers_on_a_later_attempt() -> None:
    error = ClientError(
        {"Error": {"Code": "ThrottlingException", "Message": "slow down"}}, "AssumeRole"
    )
    good_credentials = cross_account._CachedCredentials(
        access_key_id="k",
        secret_access_key="s",
        session_token="t",
        expiration=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    with (
        patch.object(
            cross_account,
            "_assume_role_once",
            side_effect=[error, error, good_credentials],
        ),
        patch.object(cross_account.time, "sleep"),
    ):
        session = cross_account.assume(
            ACCOUNT_ID, feature_id="F1", correlation_id="01JBP2VHF9K3Q0Z8R7X6M5N4A3"
        )
    assert session.get_credentials() is not None


def _create_assumable_role() -> None:
    """Set up a trust-anything role in the moto-mocked account so AssumeRole succeeds."""
    iam = boto3.client("iam", region_name="us-east-1")
    trust_policy: dict[str, Any] = {
        "Version": "2012-10-17",
        "Statement": [
            {"Effect": "Allow", "Principal": {"AWS": "*"}, "Action": "sts:AssumeRole"}
        ],
    }
    iam.create_role(
        RoleName=ROLE_NAME,
        AssumeRolePolicyDocument=json.dumps(trust_policy),
    )
