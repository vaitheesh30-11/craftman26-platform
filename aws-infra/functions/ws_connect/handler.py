"""`$connect` route for `SentinelStream` (phase-07 §4).

Auth-gated by the same `api_authorizer` Lambda (a WebSocket `$connect`
route is the one place API Gateway v2 supports a REQUEST authorizer on a
WebSocket API); this handler's own job is only to persist the resolved
`connectionId` so `functions/ws_default` can look it up when Prime needs
to fan a streamed turn back out.
"""

from __future__ import annotations

import os
import time
from typing import Any

import boto3

_ddb = boto3.resource("dynamodb")
_CONNECTION_TTL_SECONDS = 4 * 60 * 60  # 4h -- longer than any single Prime turn should run


def handler(event: dict[str, Any], _context: object) -> dict[str, Any]:
    table = _ddb.Table(os.environ["SENTINEL_CONNECTIONS_TABLE"])
    request_context = event["requestContext"]
    connection_id = request_context["connectionId"]
    authorizer = request_context.get("authorizer") or {}

    table.put_item(
        Item={
            "connection_id": connection_id,
            "principal": authorizer.get("principal", "unknown"),
            "auth_kind": authorizer.get("authKind", "unknown"),
            "connected_at": int(time.time()),
            "expires_at": int(time.time()) + _CONNECTION_TTL_SECONDS,
        }
    )
    return {"statusCode": 200}
