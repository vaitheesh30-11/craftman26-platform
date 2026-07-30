from __future__ import annotations

from unittest.mock import MagicMock

from iam_sentinel_backend.ws.connect import handle_connect
from iam_sentinel_backend.ws.disconnect import handle_disconnect


def test_handle_connect_persists_resolved_principal_and_mints_a_session_id() -> None:
    connections_client = MagicMock()
    event = {
        "requestContext": {
            "connectionId": "conn-1",
            "authorizer": {
                "principal": "arn:aws:sts::111111111111:assumed-role/Foo/bar",
                "authKind": "sigv4",
            },
        }
    }

    result = handle_connect(event, connections_client=connections_client)

    assert result == {"statusCode": 200}
    connections_client.connect.assert_called_once()
    kwargs = connections_client.connect.call_args.kwargs
    assert kwargs["connection_id"] == "conn-1"
    assert kwargs["principal"] == "arn:aws:sts::111111111111:assumed-role/Foo/bar"
    assert kwargs["auth_kind"] == "sigv4"
    assert len(kwargs["session_id"]) == 26  # ULID


def test_handle_connect_defaults_to_unknown_principal_when_authorizer_context_missing() -> None:
    connections_client = MagicMock()
    event = {"requestContext": {"connectionId": "conn-2"}}

    handle_connect(event, connections_client=connections_client)

    kwargs = connections_client.connect.call_args.kwargs
    assert kwargs["principal"] == "unknown"
    assert kwargs["auth_kind"] == "unknown"


def test_handle_disconnect_deletes_the_connection_row() -> None:
    connections_client = MagicMock()
    event = {"requestContext": {"connectionId": "conn-1"}}

    result = handle_disconnect(event, connections_client=connections_client)

    assert result == {"statusCode": 200}
    connections_client.disconnect.assert_called_once_with("conn-1")
