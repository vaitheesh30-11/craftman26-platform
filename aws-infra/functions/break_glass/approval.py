"""Two-signer approval for the IAM Sentinel break-glass path (aws-infra
phase-01 §6). A single principal signing twice, or two principals signing
more than 60 seconds apart, must never approve.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import boto3

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

_TWO_SIGNER_WINDOW = timedelta(seconds=60)
_dynamodb = boto3.resource("dynamodb")


def evaluate_two_signer(
    *,
    first_principal_id: str,
    first_signed_at: datetime,
    second_principal_id: str,
    second_signed_at: datetime,
) -> bool:
    if first_principal_id == second_principal_id:
        return False
    return abs(second_signed_at - first_signed_at) <= _TWO_SIGNER_WINDOW


def handler(event: dict[str, Any], _context: object) -> dict[str, Any]:
    table: Table = _dynamodb.Table(event["table_name"])
    session_id = event["session_tag"]
    principal_id = event["principal_id"]
    now = datetime.now(UTC)

    existing = table.get_item(Key={"session_id": session_id}).get("Item")
    if existing is None:
        table.put_item(
            Item={
                "session_id": session_id,
                "first_principal_id": principal_id,
                "first_signed_at": now.isoformat(),
            }
        )
        return {"approved": False, "reason": "awaiting second signer"}

    first_principal_id = str(existing["first_principal_id"])
    approved = evaluate_two_signer(
        first_principal_id=first_principal_id,
        first_signed_at=datetime.fromisoformat(str(existing["first_signed_at"])),
        second_principal_id=principal_id,
        second_signed_at=now,
    )
    return {
        "approved": approved,
        "first_principal_id": first_principal_id,
        "second_principal_id": principal_id,
    }
