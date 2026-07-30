from __future__ import annotations

import json
from unittest.mock import MagicMock

from iam_sentinel_backend.ws.default import handle_default


def _event(connection_id: str, body: dict[str, object]) -> dict[str, object]:
    return {
        "requestContext": {
            "connectionId": connection_id,
            "domainName": "xyz.execute-api.us-east-1.amazonaws.com",
            "stage": "dev",
        },
        "body": json.dumps(body),
    }


def test_returns_early_when_connection_is_unknown() -> None:
    connections_client = MagicMock()
    connections_client.get.return_value = None
    fanout_service = MagicMock()

    result = handle_default(
        _event("conn-1", {"action": "ping"}),
        connections_client=connections_client,
        fanout_service=fanout_service,
    )

    assert result == {"statusCode": 200}
    fanout_service.send_pong.assert_not_called()


def test_ping_action_sends_pong() -> None:
    connections_client = MagicMock()
    connections_client.get.return_value = {"principal": "p", "session_id": "s1"}
    fanout_service = MagicMock()

    handle_default(
        _event("conn-1", {"action": "ping"}),
        connections_client=connections_client,
        fanout_service=fanout_service,
    )

    fanout_service.send_pong.assert_called_once_with(
        endpoint_url="https://xyz.execute-api.us-east-1.amazonaws.com/dev", connection_id="conn-1"
    )


def test_cancel_action_cancels_and_acknowledges() -> None:
    connections_client = MagicMock()
    connections_client.get.return_value = {"principal": "p", "session_id": "s1"}
    fanout_service = MagicMock()

    handle_default(
        _event("conn-1", {"action": "cancel", "correlation_id": "c1"}),
        connections_client=connections_client,
        fanout_service=fanout_service,
    )

    fanout_service.cancel.assert_called_once_with(correlation_id="c1")
    fanout_service.send_error.assert_called_once()
    assert fanout_service.send_error.call_args.kwargs["code"] == "CANCELED"
    assert fanout_service.send_error.call_args.kwargs["correlation_id"] == "c1"


def test_chat_action_streams_using_the_connection_s_own_principal_not_client_supplied() -> None:
    connections_client = MagicMock()
    connections_client.get.return_value = {
        "principal": "arn:aws:sts::111111111111:assumed-role/Foo/bar",
        "session_id": "s1",
    }
    fanout_service = MagicMock()

    # `ChatRequest` (the `query` schema) has no `principal` field at all --
    # there is no client-supplied identity to ignore, only the connection's.
    handle_default(
        _event("conn-1", {"action": "chat", "query": {"query_text": "audit passrole"}}),
        connections_client=connections_client,
        fanout_service=fanout_service,
    )

    fanout_service.stream_chat.assert_called_once()
    kwargs = fanout_service.stream_chat.call_args.kwargs
    assert kwargs["principal"] == "arn:aws:sts::111111111111:assumed-role/Foo/bar"
    assert kwargs["query_text"] == "audit passrole"


def test_bad_frame_sends_an_error_and_does_not_raise() -> None:
    connections_client = MagicMock()
    connections_client.get.return_value = {"principal": "p", "session_id": "s1"}
    fanout_service = MagicMock()
    event = {
        "requestContext": {
            "connectionId": "conn-1",
            "domainName": "xyz.execute-api.us-east-1.amazonaws.com",
            "stage": "dev",
        },
        "body": "not json",
    }

    result = handle_default(
        event, connections_client=connections_client, fanout_service=fanout_service
    )

    assert result == {"statusCode": 200}
    fanout_service.send_error.assert_called_once()
    assert fanout_service.send_error.call_args.kwargs["code"] == "BAD_FRAME"
