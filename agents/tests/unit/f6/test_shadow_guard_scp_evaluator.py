"""phase-05 §4 Step 2's algorithm, built early under F6 -- see
docs/decisions/0023. No moto needed: pure statement-matching logic.
"""

from __future__ import annotations

import pytest

from iam_sentinel_agents.tools.common.shadow_guard_scp_evaluator import (
    evaluate_action,
    LevelPolicies,
)

pytestmark = pytest.mark.unit

_ROOT_FULL_ACCESS: LevelPolicies = {
    "level": "root",
    "policies": [
        {
            "arn": "arn:aws:organizations::o-1:policy/p-full",
            "name": "FullAWSAccess",
            "document": {"Statement": [{"Effect": "Allow", "Action": "*", "Resource": "*"}]},
        }
    ],
}


def _ou_deny(action_patterns: list[str], *, sid: str = "DenyIt") -> LevelPolicies:
    return {
        "level": "ou",
        "policies": [
            {
                "arn": "arn:aws:organizations::o-1:policy/p-ou-deny",
                "name": "OuDeny",
                "document": {
                    "Statement": [
                        {"Sid": sid, "Effect": "Deny", "Action": action_patterns, "Resource": "*"}
                    ]
                },
            }
        ],
    }


def test_no_scps_at_any_level_allows_everything() -> None:
    result = evaluate_action(chain=[], action="iam:deleterole")
    assert result.allowed is True
    assert result.denying_policy_arn is None


def test_ou_level_deny_blocks_matching_action() -> None:
    chain = [_ROOT_FULL_ACCESS, _ou_deny(["iam:DeleteRole"])]

    result = evaluate_action(chain=chain, action="iam:deleterole")

    assert result.allowed is False
    assert result.denying_level == "ou"
    assert result.denying_statement_id == "DenyIt"
    assert result.denying_policy_arn == "arn:aws:organizations::o-1:policy/p-ou-deny"


def test_ou_level_deny_does_not_block_a_different_action() -> None:
    chain = [_ROOT_FULL_ACCESS, _ou_deny(["iam:DeleteRole"])]

    result = evaluate_action(chain=chain, action="s3:getobject")

    assert result.allowed is True


def test_wildcard_deny_pattern_matches_case_insensitively() -> None:
    chain = [_ROOT_FULL_ACCESS, _ou_deny(["organizations:Delete*", "organizations:Detach*"])]

    assert evaluate_action(chain=chain, action="organizations:deletepolicy").allowed is False
    assert evaluate_action(chain=chain, action="organizations:detachpolicy").allowed is False
    assert evaluate_action(chain=chain, action="organizations:listroots").allowed is True


def test_not_action_inverts_allow_matching() -> None:
    # An Allow with NotAction=["iam:*"] allows everything EXCEPT iam:* --
    # so iam:deleterole must fail to match this level's Allow set and be
    # treated as denied-by-restriction (no explicit Deny needed).
    root_not_action: LevelPolicies = {
        "level": "root",
        "policies": [
            {
                "arn": "arn:aws:organizations::o-1:policy/p-not-action",
                "name": "AllowAllExceptIam",
                "document": {
                    "Statement": [{"Effect": "Allow", "NotAction": "iam:*", "Resource": "*"}]
                },
            }
        ],
    }

    assert evaluate_action(chain=[root_not_action], action="iam:deleterole").allowed is False
    assert evaluate_action(chain=[root_not_action], action="s3:getobject").allowed is True


def test_conditioned_deny_applies_conservatively_by_default() -> None:
    conditioned_deny: LevelPolicies = {
        "level": "root",
        "policies": [
            {
                "arn": "arn:aws:organizations::o-1:policy/p-cond",
                "name": "ConditionedDeny",
                "document": {
                    "Statement": [
                        {
                            "Sid": "CondDeny",
                            "Effect": "Deny",
                            "Action": "s3:deleteobject",
                            "Resource": "*",
                            "Condition": {"StringEquals": {"aws:RequestedRegion": "eu-west-1"}},
                        }
                    ]
                },
            }
        ],
    }

    result = evaluate_action(
        chain=[conditioned_deny],
        action="s3:deleteobject",
        principal_arn="arn:aws:iam::111122223333:role/Ops",
    )

    assert result.allowed is False


def test_principal_is_aws_service_condition_exempts_service_linked_roles() -> None:
    slr_guard_deny: LevelPolicies = {
        "level": "root",
        "policies": [
            {
                "arn": "arn:aws:organizations::o-1:policy/p-slr",
                "name": "SlrGuardDeny",
                "document": {
                    "Statement": [
                        {
                            "Sid": "SlrGuard",
                            "Effect": "Deny",
                            "Action": "iam:deleteservicelinkedrole",
                            "Resource": "*",
                            "Condition": {"Bool": {"aws:PrincipalIsAWSService": "true"}},
                        }
                    ]
                },
            }
        ],
    }
    slr_arn = "arn:aws:iam::111122223333:role/aws-service-role/example.amazonaws.com/AWSServiceRoleForExample"

    slr_result = evaluate_action(
        chain=[slr_guard_deny], action="iam:deleteservicelinkedrole", principal_arn=slr_arn
    )
    non_slr_result = evaluate_action(
        chain=[slr_guard_deny],
        action="iam:deleteservicelinkedrole",
        principal_arn="arn:aws:iam::111122223333:role/Ops",
    )

    assert slr_result.allowed is True
    assert non_slr_result.allowed is False
