"""`SentinelCrossAccountRole` -- the only IAM identity Sentinel has in member
accounts (phase-08). Deployed org-wide via a `SERVICE_MANAGED` CloudFormation
StackSet with `AutoDeployment` so newly joined accounts get the role without
a manual step, plus a second, narrower StackSet for the two delegated-admin
accounts (Access Analyzer, Identity Center) that need a wider read surface.

`PermissionModel=SERVICE_MANAGED` requires "trusted access" for CloudFormation
StackSets to already be enabled in AWS Organizations, and both StackSets need
a real Organization (with member accounts and an org root/OU) to actually
deploy into -- none of which exists in this offline sandbox. This phase is
therefore built and verified synth-only / cdk-nag-only; every acceptance
criterion that requires a live StackSet operation is deferred. See ADR 0014.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import aws_cdk as cdk
from aws_cdk import Duration, Stack
from aws_cdk import aws_cloudformation as cfn
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_cloudwatch_actions as cloudwatch_actions
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_stepfunctions as sfn
from aws_cdk import aws_stepfunctions_tasks as tasks
from cdk_nag import NagSuppressions

from iam_sentinel_infra.constructs.sentinel_lambda import LAMBDA_ASSET_EXCLUDES

if TYPE_CHECKING:
    from constructs import Construct

    from iam_sentinel_infra.config import StageConfig
    from iam_sentinel_infra.stacks.lambda_stack import LambdaStack
    from iam_sentinel_infra.stacks.security_stack import SecurityStack

_FUNCTIONS_DIR = Path(__file__).resolve().parents[3] / "functions"

# Fixed literals across the platform -- `SentinelPermissionBoundary`
# (aws-infra phase-00/01) already grants every Sentinel role
# `sts:AssumeRole` on `SentinelCrossAccountRole` by this exact name, and
# `LambdaStack.SENTINEL_CROSS_ACCOUNT_ROLE_NAME` mirrors it (phase-04). Kept
# as a local constant rather than importing `LambdaStack`'s to avoid a
# stack-ordering dependency neither stack otherwise needs.
CROSS_ACCOUNT_ROLE_NAME = "SentinelCrossAccountRole"
DELEGATED_ADMIN_ROLE_NAME = "SentinelDelegatedAdminAccountRole"
_DRIFT_METRIC_NAMESPACE = "IAMSentinel/CrossAccount"
_DRIFT_METRIC_NAME = "SentinelCrossAccountDrift"


def _trust_policy(central_account_id: str) -> dict[str, Any]:
    """Phase-08 §3 verbatim: only principals in Sentinel's own central
    account, tagged `Project=IAMSentinel`, with a `Sentinel*`-named role, may
    assume this role."""
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"AWS": f"arn:aws:iam::{central_account_id}:root"},
                "Action": "sts:AssumeRole",
                "Condition": {
                    "StringEquals": {"aws:PrincipalTag/Project": "IAMSentinel"},
                    "StringLike": {
                        "aws:PrincipalArn": f"arn:aws:iam::{central_account_id}:role/Sentinel*"
                    },
                },
            }
        ],
    }


def _read_only_bundle_statements() -> list[dict[str, Any]]:
    """Phase-08 §3 verbatim Read-Only Bundle -- the permission policy every
    member account's `SentinelCrossAccountRole` carries. The two narrowly
    scoped write exceptions (`AccessAnalyzerUpdate` for F2,
    `F5ScopedPutDelete` for F5) are gated on `aws:PrincipalTag/Feature`, which
    only a specialist Lambda's own assumed-role session sets -- defense in
    depth even inside a single member account."""
    return [
        {
            "Sid": "IamRead",
            "Effect": "Allow",
            "Action": [
                "iam:List*",
                "iam:Get*",
                "iam:SimulatePrincipalPolicy",
                "iam:SimulateCustomPolicy",
                "iam:GetAccountAuthorizationDetails",
            ],
            "Resource": "*",
        },
        {
            "Sid": "OrgRead",
            "Effect": "Allow",
            "Action": ["organizations:Describe*", "organizations:List*"],
            "Resource": "*",
        },
        {
            "Sid": "AccessAnalyzerRead",
            "Effect": "Allow",
            "Action": [
                "access-analyzer:List*",
                "access-analyzer:Get*",
                "access-analyzer:CheckNoNewAccess",
                "access-analyzer:CheckAccessNotGranted",
            ],
            "Resource": "arn:aws:access-analyzer:*:*:analyzer/*",
        },
        {
            "Sid": "AccessAnalyzerUpdate",
            "Effect": "Allow",
            "Action": [
                "access-analyzer:UpdateFindings",
                "access-analyzer:CreateArchiveRule",
                "access-analyzer:UpdateArchiveRule",
            ],
            "Resource": "arn:aws:access-analyzer:*:*:analyzer/*",
            "Condition": {"StringEquals": {"aws:PrincipalTag/Feature": "F2"}},
        },
        {
            "Sid": "CloudTrailReadWrite",
            "Effect": "Allow",
            "Action": [
                "cloudtrail:GetTrail",
                "cloudtrail:GetEventSelectors",
                "cloudtrail:PutEventSelectors",
            ],
            "Resource": "arn:aws:cloudtrail:*:*:trail/*",
            "Condition": {"StringEquals": {"aws:PrincipalTag/Feature": "F3"}},
        },
        {
            "Sid": "SsoAdminReadOnly",
            "Effect": "Allow",
            "Action": ["sso:List*", "sso:Describe*"],
            "Resource": "*",
        },
        {
            "Sid": "F5ScopedPutDelete",
            "Effect": "Allow",
            "Action": ["iam:PutRolePolicy", "iam:GetRolePolicy", "iam:DeleteRolePolicy"],
            "Resource": "arn:aws:iam::*:role/aws-reserved/sso.amazonaws.com/*",
            "Condition": {
                "StringEquals": {"aws:PrincipalTag/Feature": "F5"},
                "StringLike": {"iam:PolicyName": "SENTINEL_EMERGENCY_REVOKE_*"},
            },
        },
    ]


def _role_template(
    role_name: str, *, central_account_id: str, extra_statements: list[dict[str, Any]] | None = None
) -> str:
    """Nested CloudFormation template (raw JSON, not a CDK stack) deployed by
    the StackSet into every target account. StackSets don't run CDK -- they
    take a template body string -- so this is hand-built JSON rather than an
    `aws_cdk.Stack`, matching how `guardrail_lifecycle`'s custom resource
    talks to a service CDK has no L2 for."""
    statements = _read_only_bundle_statements() + (extra_statements or [])
    template = {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Description": f"IAM Sentinel cross-account role ({role_name}), owned by aws-infra "
        "phase-08. Do not edit outside the StackSet.",
        "Resources": {
            "SentinelRole": {
                "Type": "AWS::IAM::Role",
                "Properties": {
                    "RoleName": role_name,
                    "AssumeRolePolicyDocument": _trust_policy(central_account_id),
                    "Policies": [
                        {
                            "PolicyName": "SentinelReadOnlyBundle",
                            "PolicyDocument": {"Version": "2012-10-17", "Statement": statements},
                        }
                    ],
                    "Tags": [{"Key": "Project", "Value": "IAMSentinel"}],
                },
            }
        },
    }
    return json.dumps(template)


class CrossAccountStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        stage_config: StageConfig,
        security: SecurityStack,
        lambdas: LambdaStack,
        env: cdk.Environment | None = None,
    ) -> None:
        super().__init__(scope, construct_id, env=env)
        self.stage_config = stage_config
        self.security = security
        self.lambdas = lambdas

        self.role_stack_set = self._build_role_stack_set(stage_config)
        self.delegated_admin_stack_set = self._build_delegated_admin_stack_set(stage_config)

        self.drift_detector = self._build_drift_detector(stage_config)
        self._build_drift_schedule_and_alarm(self.drift_detector)

        self.health_check_workflow = self._build_health_check_workflow(stage_config)
        self._build_new_account_rule(self.health_check_workflow)

        NagSuppressions.add_stack_suppressions(
            self,
            [
                {
                    "id": "AwsSolutions-IAM4",
                    "reason": (
                        "AWSLambdaBasicExecutionRole is CDK's default Lambda execution role "
                        "addition (CloudWatch Logs only, scoped to the function's own log group)."
                    ),
                    "appliesTo": [
                        "Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
                    ],
                },
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": (
                        "The drift detector's `cloudformation:List*`/`Describe*` surface and "
                        "`sts:AssumeRole` on `arn:aws:iam::*:role/SentinelCrossAccountRole` "
                        "are both wildcarded by design: the account-id segment is unknown "
                        "at synth time (any current or future org member account) and "
                        "`cloudwatch:PutMetricData` has no resource-level permissions at all "
                        "per AWS's own action reference."
                    ),
                },
                {
                    "id": "HIPAA.Security-LambdaInsideVPC",
                    "reason": (
                        "docs/ARCHITECTURE.md §Networking: IAM Sentinel is deliberately "
                        "VPC-less across the whole platform."
                    ),
                },
                {
                    "id": "HIPAA.Security-IAMNoInlinePolicy",
                    "reason": (
                        "CDK's auto-generated DefaultPolicy grants (sts:AssumeRole, "
                        "cloudformation:Detect*/Describe*/List*, cloudwatch:PutMetricData, "
                        "sns:Publish, and the Step Functions/EventBridge service roles CDK "
                        "itself creates for the health-check workflow); splitting each into "
                        "a managed policy adds indirection without changing the effective "
                        "grant, matching the AthenaStack precedent (ADR 0009)."
                    ),
                },
            ],
        )

    def _build_role_stack_set(self, stage_config: StageConfig) -> cfn.CfnStackSet:
        """Phase-08 §4: `SERVICE_MANAGED`, `AutoDeployment` enabled, targets
        the org root OU minus Sentinel's own central account (which already
        hosts the assuming roles and needs no read-only mirror of itself)."""
        return cfn.CfnStackSet(
            self,
            "CrossAccountRoleStackSet",
            stack_set_name=f"SentinelCrossAccountRole-{stage_config.stage}",
            permission_model="SERVICE_MANAGED",
            capabilities=["CAPABILITY_NAMED_IAM"],
            description="Deploys SentinelCrossAccountRole to every org member account "
            "except Sentinel's own central account (phase-08 §2-4).",
            template_body=_role_template(
                CROSS_ACCOUNT_ROLE_NAME, central_account_id=stage_config.account_id
            ),
            auto_deployment=cfn.CfnStackSet.AutoDeploymentProperty(
                enabled=True, retain_stacks_on_account_removal=False
            ),
            operation_preferences=cfn.CfnStackSet.OperationPreferencesProperty(
                max_concurrent_percentage=25, failure_tolerance_percentage=5
            ),
            stack_instances_group=[
                cfn.CfnStackSet.StackInstancesProperty(
                    deployment_targets=cfn.CfnStackSet.DeploymentTargetsProperty(
                        organizational_unit_ids=[stage_config.org_root_id],
                        account_filter_type="DIFFERENCE",
                        accounts=[stage_config.account_id],
                    ),
                    regions=[stage_config.region],
                )
            ],
        )

    def _build_delegated_admin_stack_set(self, stage_config: StageConfig) -> cfn.CfnStackSet:
        """Phase-08 §6: a second, narrower StackSet targeting only the two
        delegated-admin accounts (Access Analyzer, Identity Center). The
        "slightly wider Access Analyzer / SSO surface" the spec promises
        those accounts is deferred until agents phase-02 (F1, Access
        Analyzer delegated admin) and phase-03 (org-context, SSO delegated
        admin) land and specify exactly which additional actions their
        Lambdas need -- see ADR 0014. Today this role carries the same
        Read-Only Bundle as the default role."""
        accounts = sorted(
            {
                stage_config.delegated_admin_analyzer_account,
                stage_config.delegated_admin_idc_account,
            }
        )
        return cfn.CfnStackSet(
            self,
            "DelegatedAdminAccountRoleStackSet",
            stack_set_name=f"SentinelDelegatedAdminAccountRole-{stage_config.stage}",
            permission_model="SERVICE_MANAGED",
            capabilities=["CAPABILITY_NAMED_IAM"],
            description="Deploys SentinelDelegatedAdminAccountRole to the Access Analyzer "
            "and Identity Center delegated-admin accounts (phase-08 §6).",
            template_body=_role_template(
                DELEGATED_ADMIN_ROLE_NAME, central_account_id=stage_config.account_id
            ),
            auto_deployment=cfn.CfnStackSet.AutoDeploymentProperty(
                enabled=False, retain_stacks_on_account_removal=False
            ),
            operation_preferences=cfn.CfnStackSet.OperationPreferencesProperty(
                max_concurrent_percentage=100, failure_tolerance_percentage=0
            ),
            stack_instances_group=[
                cfn.CfnStackSet.StackInstancesProperty(
                    deployment_targets=cfn.CfnStackSet.DeploymentTargetsProperty(
                        accounts=accounts
                    ),
                    regions=[stage_config.region],
                )
            ],
        )

    def _build_drift_detector(self, stage_config: StageConfig) -> lambda_.Function:
        """Phase-08 §5: weekly `DetectStackSetDrift` + a
        `SentinelCrossAccountDrift` CloudWatch metric per StackSet. Uses
        `LambdaStack.new_function` (phase-04 substrate) like every other
        owning phase, per ADR 0011."""
        stack_set_arns = [
            f"arn:aws:cloudformation:{self.region}:{self.account}:stackset/"
            f"{stack_set.stack_set_name}:*"
            for stack_set in (self.role_stack_set, self.delegated_admin_stack_set)
        ]
        fn = self.lambdas.new_function(
            self,
            "DriftDetectorFn",
            code=lambda_.Code.from_asset(str(_FUNCTIONS_DIR / "crossaccount_drift_detector"), exclude=LAMBDA_ASSET_EXCLUDES),
            role_statements=[
                iam.PolicyStatement(
                    actions=[
                        "cloudformation:DetectStackSetDrift",
                        "cloudformation:DescribeStackSetOperation",
                        "cloudformation:ListStackInstances",
                    ],
                    resources=stack_set_arns,
                ),
                iam.PolicyStatement(actions=["cloudwatch:PutMetricData"], resources=["*"]),
            ],
            timeout=Duration.minutes(10),
            memory_size=256,
            reserved_concurrent_executions=1,
            alarm_topic=self.security.security_topic,
        )
        return fn.function

    def _build_drift_schedule_and_alarm(self, drift_detector: lambda_.Function) -> None:
        events.Rule(
            self,
            "DriftDetectionSchedule",
            schedule=events.Schedule.expression("cron(0 5 ? * SAT *)"),
            targets=[
                targets.LambdaFunction(
                    drift_detector,
                    event=events.RuleTargetInput.from_object(
                        {
                            "stack_set_names": [
                                self.role_stack_set.stack_set_name,
                                self.delegated_admin_stack_set.stack_set_name,
                            ]
                        }
                    ),
                )
            ],
        )
        cloudwatch.Alarm(
            self,
            "CrossAccountDriftAlarm",
            metric=cloudwatch.Metric(
                namespace=_DRIFT_METRIC_NAMESPACE,
                metric_name=_DRIFT_METRIC_NAME,
                statistic="Maximum",
                period=Duration.hours(1),
            ),
            threshold=0,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            evaluation_periods=1,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            alarm_description="A SentinelCrossAccountRole/SentinelDelegatedAdminAccountRole "
            "stack instance has drifted from its StackSet-defined template.",
        ).add_alarm_action(cloudwatch_actions.SnsAction(self.security.security_topic))

    def _build_health_check_workflow(self, stage_config: StageConfig) -> sfn.StateMachine:
        """Phase-08 §9 risk mitigation: "new-account auto-deployment fails
        silently" -> wait 30 minutes for `AutoDeployment` to finish, then try
        to assume the new role; alert on any failure instead of relying on
        someone noticing a missing role during an incident."""
        healthcheck_fn = self.lambdas.new_function(
            self,
            "HealthCheckFn",
            code=lambda_.Code.from_asset(str(_FUNCTIONS_DIR / "crossaccount_healthcheck"), exclude=LAMBDA_ASSET_EXCLUDES),
            role_statements=[
                iam.PolicyStatement(
                    actions=["sts:AssumeRole"],
                    resources=[f"arn:aws:iam::*:role/{CROSS_ACCOUNT_ROLE_NAME}"],
                )
            ],
            timeout=Duration.seconds(30),
            memory_size=256,
            alarm_topic=self.security.security_topic,
        )

        check_role = tasks.LambdaInvoke(
            self,
            "CheckRoleIsAssumable",
            lambda_function=healthcheck_fn.function,
            payload=sfn.TaskInput.from_object({"account_id.$": "$.account_id"}),
            payload_response_only=True,
        )
        alert_failure = tasks.SnsPublish(
            self,
            "AlertHealthCheckFailure",
            topic=self.security.security_topic,
            message=sfn.TaskInput.from_text(
                "SentinelCrossAccountRole health check failed 30 minutes after a new "
                "account joined the organization -- AutoDeployment may have failed."
            ),
        )
        check_role.add_catch(alert_failure, errors=["States.ALL"])

        definition = sfn.Wait(
            self, "WaitForAutoDeployment", time=sfn.WaitTime.duration(Duration.minutes(30))
        ).next(check_role)

        workflow_log_group = logs.LogGroup(
            self,
            "HealthCheckWorkflowLogs",
            retention=logs.RetentionDays.ONE_YEAR,
            encryption_key=self.security.data_key,
        )
        self.security.data_key.grant_encrypt_decrypt(
            iam.ServicePrincipal(f"logs.{self.region}.amazonaws.com")
        )
        return sfn.StateMachine(
            self,
            "HealthCheckWorkflow",
            state_machine_type=sfn.StateMachineType.STANDARD,
            definition_body=sfn.DefinitionBody.from_chainable(definition),
            timeout=Duration.minutes(40),
            tracing_enabled=True,
            logs=sfn.LogOptions(destination=workflow_log_group, level=sfn.LogLevel.ALL),
        )

    def _build_new_account_rule(self, workflow: sfn.StateMachine) -> None:
        """`CreateAccountResult` is an Organizations service event delivered
        via CloudTrail management events (the same default-event-bus path
        ADR 0002 already established for break-glass -- no new Trail)."""
        events.Rule(
            self,
            "NewAccountJoinedRule",
            event_pattern=events.EventPattern(
                source=["aws.organizations"],
                detail_type=["AWS Service Event via CloudTrail"],
                detail={"eventName": ["CreateAccountResult"]},
            ),
            targets=[
                targets.SfnStateMachine(
                    workflow,
                    input=events.RuleTargetInput.from_object(
                        {
                            "account_id": events.EventField.from_path(
                                "$.detail.serviceEventDetails.createAccountStatus.accountId"
                            )
                        }
                    ),
                )
            ],
        )
