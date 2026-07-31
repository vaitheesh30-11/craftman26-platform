from __future__ import annotations

import pytest

from iam_sentinel_agents.tools.f7.minimal_fix import build_minimal_fix, is_valid_scp_statement

pytestmark = pytest.mark.unit


def test_removes_action_from_a_multi_action_deny_list() -> None:
    fix = build_minimal_fix(
        action="ec2:RunInstances",
        denying_statement_id="DenyEc2",
        denying_action_patterns=["ec2:RunInstances", "ec2:TerminateInstances"],
        denying_resource_patterns=["*"],
    )
    assert fix["strategy"] == "remove_action_from_list"
    assert fix["patched_statement"]["Action"] == ["ec2:TerminateInstances"]
    assert is_valid_scp_statement(fix["patched_statement"])


def test_wildcard_deny_falls_back_to_condition_exemption() -> None:
    fix = build_minimal_fix(
        action="s3:GetObject",
        denying_statement_id="DenyS3",
        denying_action_patterns=["s3:*"],
        denying_resource_patterns=["*"],
    )
    assert fix["strategy"] == "condition_exemption"
    patched = fix["patched_statement"]
    assert patched["Action"] == ["s3:*"]
    assert "Condition" in patched
    assert is_valid_scp_statement(patched)


def test_single_item_list_equal_to_action_also_uses_condition_exemption() -> None:
    # Removing the only action would leave an empty Action list -- not a
    # meaningful SCP statement -- so this must not take the removal branch.
    fix = build_minimal_fix(
        action="ec2:RunInstances",
        denying_statement_id="DenyEc2Only",
        denying_action_patterns=["ec2:RunInstances"],
        denying_resource_patterns=["*"],
    )
    assert fix["strategy"] == "condition_exemption"
    assert is_valid_scp_statement(fix["patched_statement"])


@pytest.mark.parametrize(
    ("statement", "expected"),
    [
        ({"Effect": "Deny", "Action": ["a:b"], "Resource": "*"}, True),
        ({"Effect": "Deny", "NotAction": ["a:b"], "Resource": "*"}, True),
        ({"Effect": "Deny", "Action": ["a:b"], "NotAction": ["c:d"], "Resource": "*"}, False),
        ({"Effect": "Deny", "Resource": "*"}, False),
        ({"Effect": "Maybe", "Action": ["a:b"], "Resource": "*"}, False),
        ({"Effect": "Deny", "Action": ["a:b"]}, False),
    ],
)
def test_is_valid_scp_statement(statement: dict[str, object], expected: bool) -> None:
    assert is_valid_scp_statement(statement) is expected
