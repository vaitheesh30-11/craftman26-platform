"""`$disconnect` route for `SentinelStream` (phase-07 §4): removes the
`connectionId` row `ws_connect` wrote. Best-effort per the WebSocket spec
(a client that never sent `$connect` successfully has nothing to clean up)
-- `ConditionExpression` is deliberately omitted so a delete of an
already-absent item is a no-op, not an error.
"""

from __future__ import annotations

import os
from typing import Any

import boto3

_ddb = boto3.resource("dynamodb")


def handler(event: dict[str, Any], _context: object) -> dict[str, Any]:
    table = _ddb.Table(os.environ["SENTINEL_CONNECTIONS_TABLE"])
    connection_id = event["requestContext"]["connectionId"]
    table.delete_item(Key={"connection_id": connection_id})
    return {"statusCode": 200}
