"""moto has no `apigatewaymanagementapi` backend, so this client is tested
against a mocked `boto3.client` the same way `aws-infra/tests/unit/
test_ws_handlers.py` tests the phase-07 `ws_default` stub.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from iam_sentinel_adapters.apigw.management import ManagementApiClient
from iam_sentinel_adapters.errors import ConnectionGoneError, NetworkError, ThrottlingError


def _client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "boom"}}, "PostToConnection")


def test_post_to_connection_calls_boto_client_once_per_endpoint() -> None:
    mock_boto_client = MagicMock()
    client = ManagementApiClient()

    with patch("boto3.client", return_value=mock_boto_client) as mock_ctor:
        client.post_to_connection(
            endpoint_url="https://a.example.com/dev", connection_id="conn-1", data=b"hi"
        )
        client.post_to_connection(
            endpoint_url="https://a.example.com/dev", connection_id="conn-2", data=b"there"
        )

    mock_ctor.assert_called_once()
    assert mock_boto_client.post_to_connection.call_count == 2


def test_gone_exception_is_translated_to_connection_gone_error() -> None:
    mock_boto_client = MagicMock()
    mock_boto_client.post_to_connection.side_effect = _client_error("GoneException")
    client = ManagementApiClient()

    with patch("boto3.client", return_value=mock_boto_client), pytest.raises(ConnectionGoneError):
        client.post_to_connection(
            endpoint_url="https://a.example.com/dev", connection_id="conn-1", data=b"hi"
        )


def test_throttling_exception_is_translated_to_throttling_error() -> None:
    mock_boto_client = MagicMock()
    mock_boto_client.post_to_connection.side_effect = _client_error("ThrottlingException")
    client = ManagementApiClient()

    with patch("boto3.client", return_value=mock_boto_client), pytest.raises(ThrottlingError):
        client.post_to_connection(
            endpoint_url="https://a.example.com/dev", connection_id="conn-1", data=b"hi"
        )


def test_other_client_error_is_translated_to_network_error() -> None:
    mock_boto_client = MagicMock()
    mock_boto_client.post_to_connection.side_effect = _client_error("InternalServerErrorException")
    client = ManagementApiClient()

    with patch("boto3.client", return_value=mock_boto_client), pytest.raises(NetworkError):
        client.post_to_connection(
            endpoint_url="https://a.example.com/dev", connection_id="conn-1", data=b"hi"
        )


def test_forget_drops_the_cached_client_so_a_later_call_rebuilds_it() -> None:
    mock_boto_client = MagicMock()
    client = ManagementApiClient()

    with patch("boto3.client", return_value=mock_boto_client) as mock_ctor:
        client.post_to_connection(
            endpoint_url="https://a.example.com/dev", connection_id="conn-1", data=b"hi"
        )
        client.forget("https://a.example.com/dev")
        client.post_to_connection(
            endpoint_url="https://a.example.com/dev", connection_id="conn-1", data=b"hi"
        )

    assert mock_ctor.call_count == 2
