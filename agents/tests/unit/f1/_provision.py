"""Provisions a moto-mocked IAM account from one of the golden fixtures
under `tests/unit/f1/fixtures/` (phase-02 §8). Not a test module itself
(leading underscore keeps pytest from collecting it).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from mypy_boto3_iam.client import IAMClient

FIXTURES_DIR = Path(__file__).parent / "fixtures"

_DEFAULT_TRUST_POLICY = {
    "Version": "2012-10-17",
    "Statement": [{"Effect": "Allow", "Principal": {"AWS": "*"}, "Action": "sts:AssumeRole"}],
}


def load_fixture(name: str) -> dict[str, Any]:
    return dict(json.loads((FIXTURES_DIR / f"{name}.json").read_text(encoding="utf-8")))


def provision(iam: IAMClient, fixture: dict[str, Any]) -> None:
    for user in fixture.get("users", []):
        iam.create_user(UserName=user["name"])
        for policy in user.get("inline_policies", []):
            iam.put_user_policy(
                UserName=user["name"],
                PolicyName=policy["name"],
                PolicyDocument=json.dumps(policy["document"]),
            )
        for policy_arn in user.get("attached_policy_arns", []):
            iam.attach_user_policy(UserName=user["name"], PolicyArn=policy_arn)

    for role in fixture.get("roles", []):
        iam.create_role(
            RoleName=role["name"],
            AssumeRolePolicyDocument=json.dumps(role.get("trust_policy", _DEFAULT_TRUST_POLICY)),
        )
        for policy in role.get("inline_policies", []):
            iam.put_role_policy(
                RoleName=role["name"],
                PolicyName=policy["name"],
                PolicyDocument=json.dumps(policy["document"]),
            )
        for policy_arn in role.get("attached_policy_arns", []):
            iam.attach_role_policy(RoleName=role["name"], PolicyArn=policy_arn)
