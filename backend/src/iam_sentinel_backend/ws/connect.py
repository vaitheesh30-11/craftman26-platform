"""`$connect` route (phase-02 §4 step 1).

JWT validation itself already happened by the time this runs: `aws-infra`
phase-07 wires `SentinelStream`'s `$connect` route to a `WebSocketLambdaAuthorizer`
(the one WebSocket route API Gateway v2 lets carry a REQUEST authorizer), so
`event["requestContext"]["authorizer"]` already carries the resolved
`principal`/`authKind` -- the same contract `aws-infra`'s existing
`functions/ws_connect/handler.py` stub relies on. This module's own job is
minting the session identity (`session_id`, a fresh ULID per phase-02 §2)
and persisting the connection row through the adapters boundary.
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from iam_sentinel_backend.deps import get_connections_client
from iam_sentinel_backend.ids import new_ulid

if TYPE_CHECKING:
    from iam_sentinel_adapters.ddb.connections import ConnectionsClient


def handler(event: dict[str, Any], _context: object) -> dict[str, Any]:
    """Real Lambda entrypoint. See module docstring re: aws-infra wiring."""
    return handle_connect(event, connections_client=get_connections_client())


def handle_connect(
    event: dict[str, Any], *, connections_client: ConnectionsClient
) -> dict[str, Any]:
    request_context = event["requestContext"]
    connection_id = request_context["connectionId"]
    authorizer = request_context.get("authorizer") or {}

    connections_client.connect(
        connection_id=connection_id,
        principal=authorizer.get("principal", "unknown"),
        session_id=new_ulid(),
        auth_kind=authorizer.get("authKind", "unknown"),
    )
    return {"statusCode": 200}
