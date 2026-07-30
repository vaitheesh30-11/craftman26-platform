from __future__ import annotations

import json

import pytest

from iam_sentinel_backend.ws.protocol import (
    CancelFrame,
    ChatFrame,
    encode_event,
    parse_frame,
    PingFrame,
    WsProtocolError,
)


def test_parse_chat_frame() -> None:
    frame = parse_frame(json.dumps({"action": "chat", "query": {"query_text": "audit passrole"}}))

    assert isinstance(frame, ChatFrame)
    assert frame.query.query_text == "audit passrole"


def test_parse_cancel_frame() -> None:
    frame = parse_frame(json.dumps({"action": "cancel", "correlation_id": "corr-1"}))

    assert isinstance(frame, CancelFrame)
    assert frame.correlation_id == "corr-1"


def test_parse_ping_frame() -> None:
    frame = parse_frame(json.dumps({"action": "ping"}))

    assert isinstance(frame, PingFrame)


def test_parse_frame_rejects_invalid_json() -> None:
    with pytest.raises(WsProtocolError):
        parse_frame("not json")


def test_parse_frame_rejects_non_object_body() -> None:
    with pytest.raises(WsProtocolError):
        parse_frame(json.dumps(["chat"]))


def test_parse_frame_rejects_unknown_action() -> None:
    with pytest.raises(WsProtocolError):
        parse_frame(json.dumps({"action": "delete_everything"}))


def test_parse_frame_rejects_missing_action() -> None:
    with pytest.raises(WsProtocolError):
        parse_frame(json.dumps({"query": {"query_text": "x"}}))


def test_parse_chat_frame_rejects_missing_query() -> None:
    with pytest.raises(WsProtocolError):
        parse_frame(json.dumps({"action": "chat"}))


def test_encode_event_with_string_payload() -> None:
    encoded = encode_event("progress", "one short sentence")

    assert encoded == b"event: progress\ndata: one short sentence\n\n"


def test_encode_event_with_dict_payload_is_json() -> None:
    encoded = encode_event(
        "error", {"code": "CANCELED", "message": "canceled", "correlation_id": "c1"}
    )

    assert encoded.startswith(b"event: error\ndata: ")
    payload = json.loads(encoded.decode().removeprefix("event: error\ndata: ").strip())
    assert payload == {"code": "CANCELED", "message": "canceled", "correlation_id": "c1"}
