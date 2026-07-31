"""Pure unit tests for `tools/common/scp_engine.py` -- constructs
`ScpLevelChain`/`ScpPolicy` directly (no AWS calls needed to exercise the
engine's own algorithm).
"""

from __future__ import annotations

import pytest

from iam_sentinel_agents.tools.common.scp_engine import (
    compute_effective_policy,
    find_collisions,
    local_allow_set,
    ScpLevelChain,
    ScpPolicy,
)

pytestmark = pytest.mark.unit


def _full_aws_access() -> ScpPolicy:
    return ScpPolicy(
        policy_id="p-FullAWSAccess",
        name="FullAWSAccess",
        arn="arn:aws:organizations::aws:policy/service_control_policy/p-FullAWSAccess",
        document={
            "Version": "2012-10-17",
            "Statement": [{"Effect": "Allow", "Action": "*", "Resource": "*"}],
        },
    )


def _policy(*, policy_id: str, name: str, statements: list[dict[str, object]]) -> ScpPolicy:
    return ScpPolicy(
        policy_id=policy_id,
        name=name,
        arn=f"arn:aws:organizations::123456789012:policy/o-test/service_control_policy/{policy_id}",
        document={"Version": "2012-10-17", "Statement": statements},
    )


def test_classic_collision_root_deny_ou_allow() -> None:
    root = ScpLevelChain(
        level="root",
        target_id="r-1",
        policies=[
            _full_aws_access(),
            _policy(
                policy_id="p-deny",
                name="RootDenyRunInstances",
                statements=[
                    {
                        "Sid": "DenyRunInstances",
                        "Effect": "Deny",
                        "Action": ["ec2:RunInstances"],
                        "Resource": "*",
                    }
                ],
            ),
        ],
    )
    ou = ScpLevelChain(
        level="ou",
        target_id="ou-1",
        policies=[
            _full_aws_access(),
            _policy(
                policy_id="p-allow",
                name="OuAllowRunInstances",
                statements=[
                    {
                        "Sid": "AllowRunInstances",
                        "Effect": "Allow",
                        "Action": ["ec2:RunInstances"],
                        "Resource": "*",
                    }
                ],
            ),
        ],
    )
    account = ScpLevelChain(
        level="account", target_id="123456789012", policies=[_full_aws_access()]
    )

    result = compute_effective_policy([root, ou, account])
    effective_actions = result["effective_policy"]["Statement"][0]["Action"]
    assert "ec2:RunInstances" not in effective_actions  # deny wins

    collisions = find_collisions(result["provenance"])
    assert len(collisions) == 1
    collision = collisions[0]
    assert collision["action"] == "ec2:RunInstances"
    assert collision["denied_at_level"] == "root"
    assert collision["allowed_at_level"] == "ou"
    assert collision["denying_statement_id"] == "DenyRunInstances"


def test_clean_chain_full_aws_access_only_has_no_collisions() -> None:
    levels = [
        ScpLevelChain(level="root", target_id="r-1", policies=[_full_aws_access()]),
        ScpLevelChain(level="account", target_id="123456789012", policies=[_full_aws_access()]),
    ]
    result = compute_effective_policy(levels)
    assert result["candidate_actions"] == []
    assert result["effective_policy"]["Statement"][0]["Action"] == []
    assert find_collisions(result["provenance"]) == []


def test_same_level_allow_and_deny_pair_is_not_a_collision() -> None:
    ou = ScpLevelChain(
        level="ou",
        target_id="ou-1",
        policies=[
            _policy(
                policy_id="p-allow",
                name="OuAllowCreateUser",
                statements=[
                    {
                        "Sid": "AllowCreateUser",
                        "Effect": "Allow",
                        "Action": ["iam:CreateUser"],
                        "Resource": "*",
                    }
                ],
            ),
            _policy(
                policy_id="p-deny",
                name="OuDenyCreateUser",
                statements=[
                    {
                        "Sid": "DenyCreateUser",
                        "Effect": "Deny",
                        "Action": ["iam:CreateUser"],
                        "Resource": "*",
                    }
                ],
            ),
        ],
    )
    account = ScpLevelChain(
        level="account", target_id="123456789012", policies=[_full_aws_access()]
    )

    result = compute_effective_policy([ou, account])
    assert find_collisions(result["provenance"]) == []
    # Still denied in the effective policy -- deny still wins locally, it's
    # just not reported as a cross-level "collision".
    assert "iam:CreateUser" not in result["effective_policy"]["Statement"][0]["Action"]


def test_wildcard_deny_matches_a_more_specific_allow() -> None:
    root = ScpLevelChain(
        level="root",
        target_id="r-1",
        policies=[
            _full_aws_access(),
            _policy(
                policy_id="p-deny",
                name="RootDenyS3Wildcard",
                statements=[
                    {"Sid": "DenyS3", "Effect": "Deny", "Action": ["s3:*"], "Resource": "*"}
                ],
            ),
        ],
    )
    ou = ScpLevelChain(
        level="ou",
        target_id="ou-1",
        policies=[
            _full_aws_access(),
            _policy(
                policy_id="p-allow",
                name="OuAllowGetObject",
                statements=[
                    {
                        "Sid": "AllowGetObject",
                        "Effect": "Allow",
                        "Action": ["s3:GetObject"],
                        "Resource": "*",
                    }
                ],
            ),
        ],
    )
    result = compute_effective_policy([root, ou])
    collisions = find_collisions(result["provenance"])
    assert len(collisions) == 1
    assert collisions[0]["action"] == "s3:GetObject"
    assert collisions[0]["denying_action_patterns"] == ["s3:*"]


def test_effective_policy_is_a_subset_of_every_levels_local_allow_set() -> None:
    root = ScpLevelChain(
        level="root",
        target_id="r-1",
        policies=[
            _full_aws_access(),
            _policy(
                policy_id="p-deny",
                name="RootDeny",
                statements=[
                    {"Sid": "D", "Effect": "Deny", "Action": ["ec2:RunInstances"], "Resource": "*"}
                ],
            ),
        ],
    )
    ou = ScpLevelChain(
        level="ou",
        target_id="ou-1",
        policies=[
            _full_aws_access(),
            _policy(
                policy_id="p-allow",
                name="OuAllow",
                statements=[
                    {"Sid": "A", "Effect": "Allow", "Action": ["ec2:RunInstances"], "Resource": "*"}
                ],
            ),
        ],
    )
    levels = [root, ou]
    result = compute_effective_policy(levels)
    effective_actions = set(result["effective_policy"]["Statement"][0]["Action"])
    for level in levels:
        allowed = local_allow_set(level)
        if allowed is None:  # unrestricted level -- no constraint to check
            continue
        assert effective_actions <= allowed
