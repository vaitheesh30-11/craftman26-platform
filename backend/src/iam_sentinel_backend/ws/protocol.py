"""Wire frames for `SentinelStream`'s `$default` route (phase-02 §3).

The client-to-server frames are plain JSON envelopes (`{"action": ...}`);
the server-to-client frames are the SSE-flavored text blocks the spec
documents literally (`event: <name>\\ndata: <payload>\\n\\n`) even though
they travel over a WebSocket data frame rather than an HTTP response body --
that shape is this phase's own protocol choice, not borrowed HTTP semantics,
and `encode_event` reproduces it exactly so a client can reuse an
off-the-shelf SSE parser against the frame's `data` payload.
"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import Field, ValidationError

from iam_sentinel_backend.schemas.chat import ChatRequest
from iam_sentinel_backend.schemas.common import RequestBase


class WsProtocolError(Exception):
    """A client frame failed to parse as one of the three known actions."""


class ChatFrame(RequestBase):
    action: Literal["chat"]
    query: ChatRequest


class CancelFrame(RequestBase):
    action: Literal["cancel"]
    correlation_id: str = Field(min_length=1)


class PingFrame(RequestBase):
    action: Literal["ping"]


IncomingFrame = ChatFrame | CancelFrame | PingFrame

_FRAME_TYPES: dict[str, type[ChatFrame] | type[CancelFrame] | type[PingFrame]] = {
    "chat": ChatFrame,
    "cancel": CancelFrame,
    "ping": PingFrame,
}


def parse_frame(raw: str) -> IncomingFrame:
    try:
        body = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise WsProtocolError(f"frame is not valid JSON: {exc}") from exc

    if not isinstance(body, dict):
        raise WsProtocolError("frame must be a JSON object")

    action = body.get("action")
    frame_type = _FRAME_TYPES.get(action) if isinstance(action, str) else None
    if frame_type is None:
        raise WsProtocolError(f"unknown or missing action {action!r}; expected chat|cancel|ping")

    try:
        return frame_type.model_validate(body)
    except ValidationError as exc:
        raise WsProtocolError(f"invalid {action!r} frame: {exc}") from exc


def encode_event(event: str, data: str | dict[str, object]) -> bytes:
    payload = data if isinstance(data, str) else json.dumps(data, default=str)
    return f"event: {event}\ndata: {payload}\n\n".encode()
