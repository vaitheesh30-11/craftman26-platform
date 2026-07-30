"""`$disconnect` route (phase-02 §4 step 3): removes the `SentinelConnections`
row `ws/connect.py` wrote. Best-effort, matching the WebSocket spec and
`ConnectionsClient.disconnect`'s own idempotent delete -- a client that never
completed `$connect` has nothing to clean up. No message-level cleanup: a
pending Prime turn dispatched before disconnect completes and its output is
discarded, per phase-02 §4 step 3's documented behavior.
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from iam_sentinel_backend.deps import get_connections_client

if TYPE_CHECKING:
    from iam_sentinel_adapters.ddb.connections import ConnectionsClient


def handler(event: dict[str, Any], _context: object) -> dict[str, Any]:
    """Real Lambda entrypoint. See connect.py's module docstring re: aws-infra wiring."""
    return handle_disconnect(event, connections_client=get_connections_client())


def handle_disconnect(
    event: dict[str, Any], *, connections_client: ConnectionsClient
) -> dict[str, Any]:
    connection_id = event["requestContext"]["connectionId"]
    connections_client.disconnect(connection_id)
    return {"statusCode": 200}
