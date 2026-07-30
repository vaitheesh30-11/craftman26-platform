from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import requests

from iam_sentinel_adapters.errors import AccessDeniedError, NetworkError
from iam_sentinel_adapters.sts import StsClient


def _fake_response(status_code: int, json_body: dict[str, object] | None = None, text: str = "") -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.text = text
    if json_body is not None:
        response.json.return_value = json_body
    return response


def test_verify_signed_request_returns_caller_identity() -> None:
    session = MagicMock()
    session.get.return_value = _fake_response(
        200,
        {
            "GetCallerIdentityResponse": {
                "GetCallerIdentityResult": {
                    "Arn": "arn:aws:iam::111122223333:user/alice",
                    "Account": "111122223333",
                    "UserId": "AIDAEXAMPLE",
                }
            }
        },
    )
    client = StsClient(session=session)

    identity = client.verify_signed_request(headers={"Authorization": "AWS4-HMAC-SHA256 ..."})

    assert identity == {
        "arn": "arn:aws:iam::111122223333:user/alice",
        "account": "111122223333",
        "user_id": "AIDAEXAMPLE",
    }
    session.get.assert_called_once()
    called_url = session.get.call_args.args[0]
    assert "sts.us-east-1.amazonaws.com" in called_url


def test_verify_signed_request_rejects_forged_signature() -> None:
    session = MagicMock()
    session.get.return_value = _fake_response(403, text="SignatureDoesNotMatch")
    client = StsClient(session=session)

    with pytest.raises(AccessDeniedError):
        client.verify_signed_request(headers={"Authorization": "AWS4-HMAC-SHA256 forged"})


def test_verify_signed_request_wraps_connection_failure() -> None:
    session = MagicMock()
    session.get.side_effect = requests.ConnectionError("boom")
    client = StsClient(session=session)

    with pytest.raises(NetworkError):
        client.verify_signed_request(headers={})


def test_whoami_returns_own_identity() -> None:
    boto_client = MagicMock()
    boto_client.get_caller_identity.return_value = {
        "Arn": "arn:aws:sts::111122223333:assumed-role/SentinelBackendLambda/req",
        "Account": "111122223333",
        "UserId": "AROAEXAMPLE:req",
    }
    client = StsClient(client=boto_client)

    identity = client.whoami()

    assert identity["arn"].startswith("arn:aws:sts::111122223333:assumed-role/SentinelBackendLambda")
