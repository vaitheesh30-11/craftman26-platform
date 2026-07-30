"""`$default` route (phase-02 §4 step 2): dispatches an inbound frame to the
`chat`/`cancel`/`ping` action it names.

The connection's `principal`/`session_id` are read from `SentinelConnections`
by `connection_id` -- never from the client-supplied frame body -- which is
what makes the phase-02 §8 "cross-connection principal leakage" risk
structurally impossible here rather than merely checked.
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from iam_sentinel_backend.deps import get_connections_client, get_stream_fanout_service
from iam_sentinel_backend.ids import new_ulid
from iam_sentinel_backend.ws.protocol import (
    CancelFrame,
    ChatFrame,
    parse_frame,
    PingFrame,
    WsProtocolError,
)

if TYPE_CHECKING:
    from iam_sentinel_adapters.ddb.connections import ConnectionsClient

    from iam_sentinel_backend.ws.fanout import StreamFanoutService


def handler(event: dict[str, Any], _context: object) -> dict[str, Any]:
    """Real Lambda entrypoint. See connect.py's module docstring re: aws-infra wiring."""
    return handle_default(
        event,
        connections_client=get_connections_client(),
        fanout_service=get_stream_fanout_service(),
    )


def _endpoint_url(request_context: dict[str, Any]) -> str:
    return f"https://{request_context['domainName']}/{request_context['stage']}"


def handle_default(
    event: dict[str, Any],
    *,
    connections_client: ConnectionsClient,
    fanout_service: StreamFanoutService,
) -> dict[str, Any]:
    request_context = event["requestContext"]
    connection_id = request_context["connectionId"]
    endpoint_url = _endpoint_url(request_context)

    connection = connections_client.get(connection_id)
    if connection is None:
        # The connection row expired (TTL) or never landed (a `$connect`/
        # `$default` race) -- there is no identity to bind this frame to and
        # no point posting an error back to a connection we cannot vouch for.
        return {"statusCode": 200}

    try:
        frame = parse_frame(event.get("body") or "{}")
    except WsProtocolError as exc:
        fanout_service.send_error(
            endpoint_url=endpoint_url,
            connection_id=connection_id,
            code="BAD_FRAME",
            message=str(exc),
        )
        return {"statusCode": 200}

    if isinstance(frame, PingFrame):
        fanout_service.send_pong(endpoint_url=endpoint_url, connection_id=connection_id)
    elif isinstance(frame, CancelFrame):
        fanout_service.cancel(correlation_id=frame.correlation_id)
        fanout_service.send_error(
            endpoint_url=endpoint_url,
            connection_id=connection_id,
            code="CANCELED",
            message="canceled by client",
            correlation_id=frame.correlation_id,
        )
    elif isinstance(frame, ChatFrame):
        fanout_service.stream_chat(
            connection_id=connection_id,
            endpoint_url=endpoint_url,
            principal=connection["principal"],
            session_id=connection.get("session_id", connection_id),
            correlation_id=new_ulid(),
            query_text=frame.query.query_text,
        )

    return {"statusCode": 200}
