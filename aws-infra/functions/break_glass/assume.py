"""Issues break-glass session credentials once the two-signer workflow has
approved (aws-infra phase-01 §6). Only reached after
`approval.evaluate_two_signer` returns True; this Lambda's own execution
role is the sole principal trusted to assume `IAMSentinelBreakGlassRole`.
"""

from __future__ import annotations

from typing import Any

import boto3

_sts = boto3.client("sts")
_SESSION_DURATION_SECONDS = 900


def handler(event: dict[str, Any], _context: object) -> dict[str, Any]:
    """`event["role_arn"]` is supplied by the state machine task input, not
    an env var — the break-glass role's trust policy names this Lambda's
    execution role, so the role must exist before this function does,
    which rules out reading the role ARN back out of this function's own
    environment at deploy time.
    """
    response = _sts.assume_role(
        RoleArn=event["role_arn"],
        RoleSessionName=f"break-glass-{event['session_tag']}"[:64],
        DurationSeconds=_SESSION_DURATION_SECONDS,
        Tags=[
            {"Key": "BreakGlass", "Value": "IAMSentinel-Two-Signer"},
            {"Key": "FirstPrincipal", "Value": event["first_principal_id"]},
            {"Key": "SecondPrincipal", "Value": event["second_principal_id"]},
        ],
    )
    credentials = response["Credentials"]
    return {
        "AccessKeyId": credentials["AccessKeyId"],
        "SecretAccessKey": credentials["SecretAccessKey"],
        "SessionToken": credentials["SessionToken"],
        "Expiration": credentials["Expiration"].isoformat(),
    }
