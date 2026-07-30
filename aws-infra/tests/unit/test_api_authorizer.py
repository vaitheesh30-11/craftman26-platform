"""Pure-logic checks for the hybrid Lambda authorizer (phase-07 §6, ADR
0017 decision 1): Cognito access-token verification via `cognito-idp:
GetUser`, SigV4 relay to STS, and the Deny-on-missing/invalid-header
paths. Network calls (`cognito-idp`, the STS relay's `urllib`) are mocked
directly -- there is no live Cognito pool or STS endpoint in this sandbox.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

if TYPE_CHECKING:
    from types import ModuleType

_MODULE_PATH = Path(__file__).resolve().parents[2] / "functions" / "api_authorizer" / "handler.py"


@pytest.fixture()
def authorizer_handler() -> ModuleType:
    spec = importlib.util.spec_from_file_location("api_authorizer_handler", _MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_cognito_access_token_resolves_to_allow_policy(authorizer_handler: ModuleType) -> None:
    mock_cognito = MagicMock()
    mock_cognito.get_user.return_value = {
        "Username": "jane",
        "UserAttributes": [{"Name": "sub", "Value": "abc-123"}],
    }
    event = {
        "methodArn": "arn:aws:execute-api:us-east-1:111111111111:apiid/dev/GET/findings",
        "headers": {"Authorization": "Bearer some-access-token"},
    }

    with patch.object(authorizer_handler, "_cognito", mock_cognito):
        result = authorizer_handler.handler(event, None)

    mock_cognito.get_user.assert_called_once_with(AccessToken="some-access-token")
    assert result["principalId"] == "abc-123"
    assert result["policyDocument"]["Statement"][0]["Effect"] == "Allow"
    assert result["context"] == {"authKind": "cognito", "principal": "abc-123"}


def test_invalid_cognito_token_raises_unauthorized(authorizer_handler: ModuleType) -> None:
    mock_cognito = MagicMock()
    mock_cognito.get_user.side_effect = ClientError(
        {"Error": {"Code": "NotAuthorizedException", "Message": "invalid token"}}, "GetUser"
    )
    event = {
        "methodArn": "arn:aws:execute-api:us-east-1:111111111111:apiid/dev/GET/findings",
        "headers": {"Authorization": "Bearer bad-token"},
    }

    with (
        patch.object(authorizer_handler, "_cognito", mock_cognito),
        pytest.raises(Exception, match="Unauthorized"),
    ):
        authorizer_handler.handler(event, None)


def test_missing_authorization_header_raises_unauthorized(authorizer_handler: ModuleType) -> None:
    event = {
        "methodArn": "arn:aws:execute-api:us-east-1:111111111111:apiid/dev/GET/findings",
        "headers": {},
    }
    with pytest.raises(Exception, match="Unauthorized"):
        authorizer_handler.handler(event, None)


def test_sigv4_relay_resolves_arn_from_sts_response(authorizer_handler: ModuleType) -> None:
    body = (
        b"<GetCallerIdentityResponse><GetCallerIdentityResult>"
        b"<Arn>arn:aws:sts::222222222222:assumed-role/MachineCaller/session</Arn>"
        b"</GetCallerIdentityResult></GetCallerIdentityResponse>"
    )
    mock_response = MagicMock()
    mock_response.read.return_value = body
    mock_response.__enter__.return_value = mock_response
    mock_response.__exit__.return_value = False

    event = {
        "methodArn": "arn:aws:execute-api:us-east-1:111111111111:apiid/dev/POST/emergency/kill-session",
        "headers": {
            "Authorization": "AWS4-HMAC-SHA256 Credential=AKIA/.../sts/aws4_request, ...",
            "Host": "sts.us-east-1.amazonaws.com",
        },
    }

    with patch("urllib.request.urlopen", return_value=mock_response):
        result = authorizer_handler.handler(event, None)

    assert result["principalId"] == "arn:aws:sts::222222222222:assumed-role/MachineCaller/session"
    assert result["context"]["authKind"] == "sigv4"


def test_sigv4_relay_refuses_a_non_sts_host(authorizer_handler: ModuleType) -> None:
    event = {
        "methodArn": "arn:aws:execute-api:us-east-1:111111111111:apiid/dev/GET/findings",
        "headers": {
            "Authorization": "AWS4-HMAC-SHA256 Credential=AKIA/.../sts/aws4_request, ...",
            "Host": "evil.example.com",
        },
    }
    with pytest.raises(Exception, match="Unauthorized"):
        authorizer_handler.handler(event, None)
