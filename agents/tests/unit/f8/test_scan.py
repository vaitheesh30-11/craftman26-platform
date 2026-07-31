"""`evaluate_scp` pure computation (phase-09 §4 Steps 3-5)."""

from __future__ import annotations

import json

import pytest

from iam_sentinel_agents.tools.f8.scan import evaluate_scp

pytestmark = pytest.mark.unit


def _row(
    service_principal: str, slr_name: str, required: list[str], core: list[str]
) -> dict[str, object]:
    return {
        "service_principal": service_principal,
        "slr_name": slr_name,
        "required_actions": required,
        "optional_actions": [],
        "core_actions": core,
        "db_version": "7",
    }


_AUTOSCALING = _row(
    "autoscaling.amazonaws.com",
    "AWSServiceRoleForAutoScaling",
    ["ec2:TerminateInstances", "ec2:RunInstances", "ec2:DescribeInstances"],
    ["ec2:TerminateInstances"],
)
_NETWORK_INTERFACE_ROWS = [
    _row(
        "ecs.amazonaws.com",
        "AWSServiceRoleForECS",
        ["ec2:CreateNetworkInterface"],
        ["ec2:CreateNetworkInterface"],
    ),
    _row(
        "rds.amazonaws.com",
        "AWSServiceRoleForRDS",
        ["ec2:CreateNetworkInterface"],
        ["ec2:CreateNetworkInterface"],
    ),
    _row(
        "sagemaker.amazonaws.com",
        "AWSServiceRoleForSageMaker",
        ["ec2:CreateNetworkInterface"],
        ["ec2:CreateNetworkInterface"],
    ),
    _row(
        "lambda.amazonaws.com",
        "AWSServiceRoleForLambda",
        ["ec2:CreateNetworkInterface"],
        ["ec2:CreateNetworkInterface"],
    ),
]


def _deny_scp(action: str) -> dict[str, object]:
    return {
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Deny", "Action": action, "Resource": "*"}],
    }


def test_no_conflict_leaves_safe_scp_unmodified() -> None:
    result = evaluate_scp(_deny_scp("s3:DeleteBucket"), [_AUTOSCALING])

    assert result["conflicts"] == []
    assert result["safe_scp"]["Statement"][0].get("Condition") is None
    assert result["exceeds_size_limit"] is False
    assert result["total_slrs_checked"] == 1


def test_core_action_conflict_is_critical_and_gets_strategy_a_condition() -> None:
    result = evaluate_scp(_deny_scp("ec2:TerminateInstances"), [_AUTOSCALING])

    assert len(result["conflicts"]) == 1
    conflict = result["conflicts"][0]
    assert conflict["impact"] == "CRITICAL"
    assert conflict["service_principal"] == "autoscaling.amazonaws.com"
    assert conflict["blocked_actions"] == ["ec2:TerminateInstances"]
    assert conflict["alternative_condition"] == {"Bool": {"aws:PrincipalIsAWSService": "false"}}

    safe_statement = result["safe_scp"]["Statement"][0]
    assert safe_statement["Condition"]["ArnNotLike"]["aws:PrincipalArn"] == (
        "arn:aws:iam::*:role/aws-service-role/autoscaling.amazonaws.com/*"
    )
    # SAFETY: exemptions never add a new Allow statement.
    assert all(stmt.get("Effect") != "Allow" for stmt in result["safe_scp"]["Statement"])


def test_many_slr_conflict_on_one_statement_uses_strategy_b_and_reports_all_four() -> None:
    result = evaluate_scp(_deny_scp("ec2:CreateNetworkInterface"), _NETWORK_INTERFACE_ROWS)

    assert len(result["conflicts"]) == 4
    assert {c["service_principal"] for c in result["conflicts"]} == {
        "ecs.amazonaws.com",
        "rds.amazonaws.com",
        "sagemaker.amazonaws.com",
        "lambda.amazonaws.com",
    }
    safe_statement = result["safe_scp"]["Statement"][0]
    assert safe_statement["Condition"] == {"Bool": {"aws:PrincipalIsAWSService": "false"}}


def test_oversized_safe_scp_sets_exceeds_size_limit() -> None:
    padding_arns = [f"arn:aws:s3:::padding-bucket-{i:04d}" for i in range(400)]
    proposed_scp = {
        "Version": "2012-10-17",
        "Statement": [
            {"Effect": "Allow", "Action": "s3:GetObject", "Resource": padding_arns},
            {"Effect": "Deny", "Action": "ec2:TerminateInstances", "Resource": "*"},
        ],
    }

    result = evaluate_scp(proposed_scp, [_AUTOSCALING])

    assert result["safe_scp_bytes"] == len(json.dumps(result["safe_scp"], separators=(",", ":")))
    assert result["safe_scp_bytes"] > 5_000
    assert result["exceeds_size_limit"] is True
