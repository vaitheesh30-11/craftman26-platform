"""Contract checks for CrossAccountStack (phase-08 §3, §4, §5, §6): the
role's trust/permission policy shape, the two StackSets' deployment targets,
and the drift-detection wiring. Live StackSet operations, drift status, and
feature-tag enforcement against a real member account are deferred per
ADR 0014 -- SERVICE_MANAGED StackSets need a real AWS Organization with
trusted access enabled, which this sandbox does not have.
"""

from __future__ import annotations

import json

from aws_cdk.assertions import Match, Template

from iam_sentinel_infra.app_factory import build_app
from iam_sentinel_infra.config import load_stage_config
from iam_sentinel_infra.stacks.crossaccount_stack import (
    CROSS_ACCOUNT_ROLE_NAME,
    DELEGATED_ADMIN_ROLE_NAME,
)


def _crossaccount_template() -> Template:
    app = build_app("dev")
    stack = app.node.find_child("SentinelCrossAccount")
    return Template.from_stack(stack)


def test_role_stack_set_targets_org_root_excluding_central_account() -> None:
    template = _crossaccount_template()
    stage_config = load_stage_config("dev")

    template.has_resource_properties(
        "AWS::CloudFormation::StackSet",
        {
            "StackSetName": f"SentinelCrossAccountRole-{stage_config.stage}",
            "PermissionModel": "SERVICE_MANAGED",
            "AutoDeployment": {"Enabled": True, "RetainStacksOnAccountRemoval": False},
            "StackInstancesGroup": [
                Match.object_like(
                    {
                        "DeploymentTargets": {
                            "OrganizationalUnitIds": [stage_config.org_root_id],
                            "AccountFilterType": "DIFFERENCE",
                            "Accounts": [stage_config.account_id],
                        }
                    }
                )
            ],
        },
    )


def test_delegated_admin_stack_set_targets_both_delegated_admin_accounts() -> None:
    template = _crossaccount_template()
    stage_config = load_stage_config("dev")
    expected_accounts = sorted(
        {stage_config.delegated_admin_analyzer_account, stage_config.delegated_admin_idc_account}
    )

    template.has_resource_properties(
        "AWS::CloudFormation::StackSet",
        {
            "StackSetName": f"SentinelDelegatedAdminAccountRole-{stage_config.stage}",
            "StackInstancesGroup": [
                Match.object_like({"DeploymentTargets": {"Accounts": expected_accounts}})
            ],
        },
    )


def test_role_template_body_carries_trust_and_read_only_bundle() -> None:
    template = _crossaccount_template()
    stage_config = load_stage_config("dev")
    stack_sets = template.find_resources("AWS::CloudFormation::StackSet")
    (default_role_set,) = (
        props
        for props in stack_sets.values()
        if props["Properties"]["StackSetName"] == f"SentinelCrossAccountRole-{stage_config.stage}"
    )
    body = json.loads(default_role_set["Properties"]["TemplateBody"])
    role_props = body["Resources"]["SentinelRole"]["Properties"]

    assert role_props["RoleName"] == CROSS_ACCOUNT_ROLE_NAME
    trust_statement = role_props["AssumeRolePolicyDocument"]["Statement"][0]
    assert trust_statement["Principal"]["AWS"] == f"arn:aws:iam::{stage_config.account_id}:root"
    assert trust_statement["Condition"]["StringEquals"]["aws:PrincipalTag/Project"] == "IAMSentinel"

    sids = {
        statement["Sid"]
        for statement in role_props["Policies"][0]["PolicyDocument"]["Statement"]
    }
    assert {"IamRead", "OrgRead", "AccessAnalyzerUpdate", "F5ScopedPutDelete"} <= sids


def test_delegated_admin_role_template_uses_its_own_role_name() -> None:
    template = _crossaccount_template()
    stage_config = load_stage_config("dev")
    stack_sets = template.find_resources("AWS::CloudFormation::StackSet")
    (delegated_set,) = (
        props
        for props in stack_sets.values()
        if props["Properties"]["StackSetName"]
        == f"SentinelDelegatedAdminAccountRole-{stage_config.stage}"
    )
    body = json.loads(delegated_set["Properties"]["TemplateBody"])
    assert body["Resources"]["SentinelRole"]["Properties"]["RoleName"] == DELEGATED_ADMIN_ROLE_NAME


def test_drift_detection_scheduled_weekly_with_alarm_on_the_custom_metric() -> None:
    template = _crossaccount_template()
    template.has_resource_properties(
        "AWS::Events::Rule", {"ScheduleExpression": "cron(0 5 ? * SAT *)"}
    )
    template.has_resource_properties(
        "AWS::CloudWatch::Alarm",
        {
            "Namespace": "IAMSentinel/CrossAccount",
            "MetricName": "SentinelCrossAccountDrift",
            "ComparisonOperator": "GreaterThanThreshold",
            "Threshold": 0,
        },
    )


def test_new_account_health_check_workflow_waits_then_invokes_and_catches() -> None:
    template = _crossaccount_template()
    state_machines = template.find_resources("AWS::StepFunctions::StateMachine")
    (state_machine,) = state_machines.values()
    # `DefinitionString` is an `Fn::Join` over template fragments, not a
    # plain string -- flatten it before asserting the Wait state's duration.
    fragments = state_machine["Properties"]["DefinitionString"]["Fn::Join"][1]
    joined = "".join(fragment for fragment in fragments if isinstance(fragment, str))
    assert '"Seconds":1800' in joined
    assert "CheckRoleIsAssumable" in joined

    template.has_resource_properties(
        "AWS::Events::Rule",
        {
            "EventPattern": {
                "source": ["aws.organizations"],
                "detail": {"eventName": ["CreateAccountResult"]},
            }
        },
    )


def test_permission_boundary_allows_assuming_both_cross_account_role_names() -> None:
    app = build_app("dev")
    security_stack = app.node.find_child("SentinelSecurity")
    template = Template.from_stack(security_stack)
    template.has_resource_properties(
        "AWS::IAM::ManagedPolicy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like(
                            {
                                "Sid": "AllowCrossAccountRoleAssumption",
                                "Resource": [
                                    "arn:aws:iam::*:role/SentinelCrossAccountRole",
                                    "arn:aws:iam::*:role/SentinelDelegatedAdminAccountRole",
                                ],
                            }
                        )
                    ]
                )
            }
        },
    )
