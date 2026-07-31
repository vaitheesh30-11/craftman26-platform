"""Exemption strategy selection and merge (phase-09 §4 Step 4)."""

from __future__ import annotations

import pytest

from iam_sentinel_agents.tools.f8.exemptions import (
    apply_exemptions,
    merge_condition,
    strategy_a_condition,
)

pytestmark = pytest.mark.unit


def test_merge_condition_dedupes_instead_of_overwriting() -> None:
    statement: dict[str, object] = {"Effect": "Deny", "Action": "ec2:CreateNetworkInterface"}

    merge_condition(statement, strategy_a_condition("ecs.amazonaws.com"))
    merge_condition(statement, strategy_a_condition("rds.amazonaws.com"))
    merge_condition(
        statement, strategy_a_condition("ecs.amazonaws.com")
    )  # duplicate, must not repeat

    values = statement["Condition"]["ArnNotLike"]["aws:PrincipalArn"]  # type: ignore[index]
    assert values == [
        "arn:aws:iam::*:role/aws-service-role/ecs.amazonaws.com/*",
        "arn:aws:iam::*:role/aws-service-role/rds.amazonaws.com/*",
    ]


def test_apply_exemptions_switches_to_strategy_b_past_the_threshold() -> None:
    narrow_statement: dict[str, object] = {"Effect": "Deny", "Action": "ec2:CreateNetworkInterface"}
    apply_exemptions(narrow_statement, ["ecs.amazonaws.com", "rds.amazonaws.com"])
    assert "ArnNotLike" in narrow_statement["Condition"]  # type: ignore[operator]
    assert "Bool" not in narrow_statement["Condition"]  # type: ignore[operator]

    broad_statement: dict[str, object] = {"Effect": "Deny", "Action": "ec2:CreateNetworkInterface"}
    apply_exemptions(
        broad_statement,
        [
            "ecs.amazonaws.com",
            "rds.amazonaws.com",
            "sagemaker.amazonaws.com",
            "lambda.amazonaws.com",
        ],
    )
    assert broad_statement["Condition"] == {"Bool": {"aws:PrincipalIsAWSService": "false"}}
