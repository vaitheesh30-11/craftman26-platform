"""`$default` route for `SentinelStream` (phase-07 §4).

Per ADR 0017, this handler is intentionally a thin acknowledgement stub,
not the real Prime-streaming fan-out: `InvokeAgentWithResponseStream` +
chunk-by-chunk `PostToConnection` is `backend` phase-02's deliverable
(sprint step 22 -- the WebSocket-streaming backend Lambda), not this
CDK-only phase's. What this phase owns is the route + connection registry
plumbing everything else needs, and a liveness echo so `$default`'s wiring
is independently testable before phase-02 lands.
"""

from __future__ import annotations

import json
import os
from typing import Any

import boto3


def _management_client(event: dict[str, Any]) -> Any:
    # A fresh client per invocation, not a module-level cache: the
    # endpoint URL is derived from the *connection's* domain/stage, which
    # can differ across WebSocket stages sharing this same Lambda.
    domain = event["requestContext"]["domainName"]
    stage = event["requestContext"]["stage"]
    return boto3.client("apigatewaymanagementapi", endpoint_url=f"https://{domain}/{stage}")


def handler(event: dict[str, Any], _context: object) -> dict[str, Any]:
    connection_id = event["requestContext"]["connectionId"]
    client = _management_client(event)
    ack = {
        "type": "ack",
        "message": "frame received; streaming fan-out lands in backend phase-02",
        "table": os.environ.get("SENTINEL_CONNECTIONS_TABLE"),
    }
    client.post_to_connection(ConnectionId=connection_id, Data=json.dumps(ack).encode("utf-8"))
    return {"statusCode": 200}
