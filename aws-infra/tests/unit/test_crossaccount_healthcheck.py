"""Pure-logic checks for the new-account health-check Lambda (phase-08 §9
risk mitigation). `moto`'s STS backend doesn't model cross-account role
assumption realistically for a role that doesn't exist yet, so both
`boto3.client` calls are mocked directly.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

_MODULE_PATH = (
    Path(__file__).resolve().parents[2] / "functions" / "crossaccount_healthcheck" / "handler.py"
)


@pytest.fixture()
def healthcheck_handler():
    spec = importlib.util.spec_from_file_location("crossaccount_healthcheck_handler", _MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_check_role_is_assumable_succeeds_when_role_exists(healthcheck_handler) -> None:
    mock_sts = MagicMock()
    mock_sts.assume_role.return_value = {
        "Credentials": {
            "AccessKeyId": "AKIA",
            "SecretAccessKey": "secret",
            "SessionToken": "token",
        }
    }
    mock_member_iam = MagicMock()

    with patch("boto3.client", side_effect=[mock_sts, mock_member_iam]) as mock_client:
        assert healthcheck_handler.check_role_is_assumable("222222222222") is True

    mock_sts.assume_role.assert_called_once_with(
        RoleArn="arn:aws:iam::222222222222:role/SentinelCrossAccountRole",
        RoleSessionName="sentinel-crossaccount-healthcheck",
    )
    mock_member_iam.get_role.assert_called_once_with(RoleName="SentinelCrossAccountRole")
    assert mock_client.call_count == 2


def test_check_role_is_assumable_raises_when_role_missing(healthcheck_handler) -> None:
    mock_sts = MagicMock()
    mock_sts.assume_role.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "not authorized"}}, "AssumeRole"
    )

    with patch("boto3.client", return_value=mock_sts), pytest.raises(ClientError):
        healthcheck_handler.check_role_is_assumable("222222222222")


def test_handler_returns_account_id_and_role_present_flag(healthcheck_handler) -> None:
    with patch.object(healthcheck_handler, "check_role_is_assumable", return_value=True):
        result = healthcheck_handler.handler({"account_id": "333333333333"}, None)

    assert result == {"account_id": "333333333333", "role_present": True}
