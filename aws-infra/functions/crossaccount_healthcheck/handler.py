"""Post-account-join health check (phase-08 §9 risk mitigation): "new-account
auto-deployment fails silently" is mitigated by trying to assume
`SentinelCrossAccountRole` in the new account 30 minutes after
`CreateAccountResult` fires (the Step Functions `Wait` state that precedes
this Lambda in `crossaccount_stack.py` -- StackSet `AutoDeployment` needs
that long in the worst case) and raising if the role isn't there yet or
denies the assumption.
"""

from __future__ import annotations

from typing import Any

import boto3

_ROLE_NAME = "SentinelCrossAccountRole"
_SESSION_NAME = "sentinel-crossaccount-healthcheck"


def check_role_is_assumable(account_id: str) -> bool:
    """Raises on any STS/IAM failure so the Step Functions `Catch` can route
    to the alarm topic; returns True only on a clean assume + `GetRole`."""
    sts = boto3.client("sts")
    role_arn = f"arn:aws:iam::{account_id}:role/{_ROLE_NAME}"
    assumed = sts.assume_role(RoleArn=role_arn, RoleSessionName=_SESSION_NAME)
    credentials = assumed["Credentials"]
    member_iam = boto3.client(
        "iam",
        aws_access_key_id=credentials["AccessKeyId"],
        aws_secret_access_key=credentials["SecretAccessKey"],
        aws_session_token=credentials["SessionToken"],
    )
    member_iam.get_role(RoleName=_ROLE_NAME)
    return True


def handler(event: dict[str, Any], _context: object) -> dict[str, Any]:
    account_id = event["account_id"]
    check_role_is_assumable(account_id)
    return {"account_id": account_id, "role_present": True}
