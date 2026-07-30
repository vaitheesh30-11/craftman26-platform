"""Pure-logic checks for the three WebSocket Lambdas (phase-07 §4):
`ws_connect` persists the resolved identity, `ws_disconnect` removes it,
`ws_default` acknowledges a frame via `apigatewaymanagementapi`. `boto3`
resource/client construction is mocked directly -- no live DynamoDB table
or WebSocket connection exists in this sandbox.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

if TYPE_CHECKING:
    from types import ModuleType


def _load(module_name: str, relative_path: str) -> ModuleType:
    module_path = Path(__file__).resolve().parents[2] / relative_path
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def ws_connect_handler(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.setenv("SENTINEL_CONNECTIONS_TABLE", "SentinelConnections-dev")
    return _load("ws_connect_handler", "functions/ws_connect/handler.py")


@pytest.fixture()
def ws_disconnect_handler(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.setenv("SENTINEL_CONNECTIONS_TABLE", "SentinelConnections-dev")
    return _load("ws_disconnect_handler", "functions/ws_disconnect/handler.py")


@pytest.fixture()
def ws_default_handler(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.setenv("SENTINEL_CONNECTIONS_TABLE", "SentinelConnections-dev")
    return _load("ws_default_handler", "functions/ws_default/handler.py")


def test_connect_persists_connection_id_and_resolved_principal(
    ws_connect_handler: ModuleType,
) -> None:
    mock_table = MagicMock()
    mock_ddb = MagicMock()
    mock_ddb.Table.return_value = mock_table
    event = {
        "requestContext": {
            "connectionId": "abc123",
            "authorizer": {
                "principal": "arn:aws:sts::111111111111:assumed-role/Foo/bar",
                "authKind": "sigv4",
            },
        }
    }

    with patch.object(ws_connect_handler, "_ddb", mock_ddb):
        result = ws_connect_handler.handler(event, None)

    assert result == {"statusCode": 200}
    mock_ddb.Table.assert_called_once_with("SentinelConnections-dev")
    item = mock_table.put_item.call_args.kwargs["Item"]
    assert item["connection_id"] == "abc123"
    assert item["principal"] == "arn:aws:sts::111111111111:assumed-role/Foo/bar"
    assert item["auth_kind"] == "sigv4"


def test_connect_defaults_to_unknown_principal_when_authorizer_context_missing(
    ws_connect_handler: ModuleType,
) -> None:
    mock_table = MagicMock()
    mock_ddb = MagicMock()
    mock_ddb.Table.return_value = mock_table
    event = {"requestContext": {"connectionId": "def456"}}

    with patch.object(ws_connect_handler, "_ddb", mock_ddb):
        ws_connect_handler.handler(event, None)

    item = mock_table.put_item.call_args.kwargs["Item"]
    assert item["principal"] == "unknown"


def test_disconnect_deletes_the_connection_row(ws_disconnect_handler: ModuleType) -> None:
    mock_table = MagicMock()
    mock_ddb = MagicMock()
    mock_ddb.Table.return_value = mock_table
    event = {"requestContext": {"connectionId": "abc123"}}

    with patch.object(ws_disconnect_handler, "_ddb", mock_ddb):
        result = ws_disconnect_handler.handler(event, None)

    assert result == {"statusCode": 200}
    mock_table.delete_item.assert_called_once_with(Key={"connection_id": "abc123"})


def test_default_posts_an_ack_frame_to_the_caller(ws_default_handler: ModuleType) -> None:
    mock_client = MagicMock()
    event = {
        "requestContext": {
            "connectionId": "abc123",
            "domainName": "xyz.execute-api.us-east-1.amazonaws.com",
            "stage": "dev",
        }
    }

    with patch("boto3.client", return_value=mock_client) as mock_boto_client:
        result = ws_default_handler.handler(event, None)

    mock_boto_client.assert_called_once_with(
        "apigatewaymanagementapi",
        endpoint_url="https://xyz.execute-api.us-east-1.amazonaws.com/dev",
    )
    mock_client.post_to_connection.assert_called_once()
    assert mock_client.post_to_connection.call_args.kwargs["ConnectionId"] == "abc123"
    assert result == {"statusCode": 200}
