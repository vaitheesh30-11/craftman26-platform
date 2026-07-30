"""KMS CMKs, the Bedrock Guardrail, the Sentinel permission boundary, and
the break-glass path (phase-01). See ADR 0001 for the two acceptance
criteria (Guardrail LIVE canary, break-glass end-to-end drill) that are
deferred until a real AWS dev account exists, and ADR 0002 for why the
break-glass alarm is EventBridge-based rather than a new CloudTrail Trail.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import aws_cdk as cdk
from aws_cdk import Duration, RemovalPolicy, Stack
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_cloudwatch_actions as cloudwatch_actions
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kms as kms
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sqs as sqs
from aws_cdk import aws_ssm as ssm
from aws_cdk import aws_stepfunctions as sfn
from aws_cdk import aws_stepfunctions_tasks as tasks
from cdk_nag import NagSuppressions

from iam_sentinel_infra.constructs.guardrail_custom_resource import GuardrailCustomResource
from iam_sentinel_infra.constructs.sentinel_permission_boundary import SentinelPermissionBoundary

if TYPE_CHECKING:
    from constructs import Construct

    from iam_sentinel_infra.config import StageConfig

_FUNCTIONS_DIR = Path(__file__).resolve().parents[3] / "functions"
_CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"
_KEY_DELETION_WINDOW = Duration.days(30)


class SecurityStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        stage_config: StageConfig,
        env: cdk.Environment | None = None,
    ) -> None:
        super().__init__(scope, construct_id, env=env)
        self.stage_config = stage_config

        self.evidence_key = self._signing_key(stage_config.stage)
        self.data_key = self._encryption_key("data", stage_config.stage)
        self.kb_key = self._encryption_key("kb", stage_config.stage)

        guardrail_policy_config = json.loads(
            (_CONFIG_DIR / "guardrail_v1.json").read_text(encoding="utf-8")
        )
        self.guardrail = GuardrailCustomResource(
            self,
            "Guardrail",
            guardrail_name=f"IAMSentinelGuardrail-{stage_config.stage}",
            blocked_input_messaging=guardrail_policy_config.pop("blockedInputMessaging"),
            blocked_outputs_messaging=guardrail_policy_config.pop("blockedOutputsMessaging"),
            policy_config=guardrail_policy_config,
        )
        ssm.StringParameter(
            self,
            "GuardrailVersionParam",
            parameter_name=f"/sentinel/{stage_config.stage}/guardrail/version",
            string_value=self.guardrail.resource.get_att_string("GuardrailVersion"),
        )

        sentinel_resource_arns = [
            f"arn:aws:dynamodb:{stage_config.region}:{stage_config.account_id}:table/Sentinel*",
            f"arn:aws:s3:::sentinel-*-{stage_config.stage}",
            f"arn:aws:s3:::sentinel-*-{stage_config.stage}/*",
            f"arn:aws:kms:{stage_config.region}:{stage_config.account_id}:key/*",
            f"arn:aws:bedrock:{stage_config.region}:{stage_config.account_id}:*",
            f"arn:aws:access-analyzer:{stage_config.region}:{stage_config.account_id}:*",
        ]
        self.permission_boundary = SentinelPermissionBoundary(
            self, "PermissionBoundary", resource_prefix_arns=sentinel_resource_arns
        )
        self.permission_boundary.apply_to_scope(self)

        self._build_break_glass_path(stage_config, sentinel_resource_arns)

        NagSuppressions.add_stack_suppressions(
            self,
            [
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": (
                        "Sentinel's own permission boundary, break-glass policy, and "
                        "Guardrail lifecycle Lambda necessarily reference Sentinel-owned "
                        "resource families by wildcard suffix (table/Sentinel*, key/*, "
                        "bedrock:*) scoped to this account; the Guardrail create/update/"
                        "delete Lambda cannot know the Guardrail ARN before AWS assigns "
                        "it on first Create."
                    ),
                },
                {
                    "id": "AwsSolutions-IAM4",
                    "reason": (
                        "AWSLambdaBasicExecutionRole is CDK's default Lambda execution "
                        "role addition (CloudWatch Logs only, scoped to the function's "
                        "own log group). Replacing it with a hand-rolled equivalent adds "
                        "no additional restriction."
                    ),
                    "appliesTo": [
                        "Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
                    ],
                },
                {
                    "id": "HIPAA.Security-IAMNoInlinePolicy",
                    "reason": (
                        "These are CDK's auto-generated DefaultPolicy grants (DDB "
                        "read/write, sts:AssumeRole) scoped to a single resource per "
                        "statement; splitting each into its own managed policy adds a "
                        "layer of indirection without changing the effective grant."
                    ),
                },
                {
                    "id": "HIPAA.Security-LambdaInsideVPC",
                    "reason": (
                        "docs/ARCHITECTURE.md §Networking: IAM Sentinel is deliberately "
                        "VPC-less across the whole platform (control-plane AWS API calls "
                        "only); a VPC would add cold-start latency and NAT cost with no "
                        "corresponding security benefit for this workload."
                    ),
                },
                {
                    "id": "HIPAA.Security-LambdaConcurrency",
                    "reason": (
                        "Reserved concurrency of 5 is set on every Lambda in this stack; "
                        "cdk-nag's HIPAA rule flags the property name it expects "
                        "(`reservedConcurrentExecutions`) is present, this is a known "
                        "false-positive against the current cdk-nag/aws-cdk-lib pairing."
                    ),
                },
                {
                    "id": "HIPAA.Security-IAMPolicyNoStatementsWithFullAccess",
                    "reason": (
                        "aws-infra/docs/phase-01-security-stack.txt §5-6 explicitly "
                        "specifies the permission boundary and break-glass policy as "
                        "service-action wildcards (bedrock:*, dynamodb:*, s3:*, kms:*) "
                        "scoped by resource ARN to Sentinel's own resource families, not "
                        "by action — least privilege here is enforced on the resource "
                        "axis, which this rule does not evaluate."
                    ),
                },
                {
                    "id": "HIPAA.Security-DynamoDBInBackupPlan",
                    "reason": (
                        "See docs/decisions/0003-aws-infra-phase-01-defer-aws-backup-plan.md "
                        "-- PITR is enabled on this table; an org-wide AWS Backup plan "
                        "covering every Sentinel table lands once aws-infra phase-02 "
                        "adds the rest of them."
                    ),
                },
            ],
        )

    def _signing_key(self, stage: str) -> kms.Key:
        return kms.Key(
            self,
            "EvidenceKey",
            alias=f"sentinel/evidence-{stage}",
            key_usage=kms.KeyUsage.SIGN_VERIFY,
            key_spec=kms.KeySpec.RSA_4096,
            pending_window=_KEY_DELETION_WINDOW,
            removal_policy=RemovalPolicy.RETAIN,
        )

    def _encryption_key(self, purpose: str, stage: str) -> kms.Key:
        return kms.Key(
            self,
            f"{purpose.capitalize()}Key",
            alias=f"sentinel/{purpose}-{stage}",
            key_usage=kms.KeyUsage.ENCRYPT_DECRYPT,
            key_spec=kms.KeySpec.SYMMETRIC_DEFAULT,
            enable_key_rotation=True,
            pending_window=_KEY_DELETION_WINDOW,
            removal_policy=RemovalPolicy.RETAIN,
        )

    def _build_break_glass_path(
        self, stage_config: StageConfig, sentinel_resource_arns: list[str]
    ) -> None:
        sessions_table = dynamodb.Table(
            self,
            "BreakGlassSessions",
            partition_key=dynamodb.Attribute(name="session_id", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            encryption=dynamodb.TableEncryption.CUSTOMER_MANAGED,
            encryption_key=self.data_key,
            point_in_time_recovery=True,
            time_to_live_attribute="expires_at",
            removal_policy=RemovalPolicy.RETAIN,
        )

        approval_dlq = sqs.Queue(
            self, "BreakGlassApprovalDlq", retention_period=Duration.days(14), enforce_ssl=True
        )
        approval_fn = lambda_.Function(
            self,
            "BreakGlassApprovalFn",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            handler="approval.handler",
            code=lambda_.Code.from_asset(str(_FUNCTIONS_DIR / "break_glass")),
            timeout=Duration.seconds(10),
            reserved_concurrent_executions=5,
            dead_letter_queue=approval_dlq,
            environment={"SENTINEL_STAGE": stage_config.stage},
        )
        sessions_table.grant_read_write_data(approval_fn)

        assume_dlq = sqs.Queue(
            self, "BreakGlassAssumeDlq", retention_period=Duration.days(14), enforce_ssl=True
        )
        assume_fn = lambda_.Function(
            self,
            "BreakGlassAssumeFn",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            handler="assume.handler",
            code=lambda_.Code.from_asset(str(_FUNCTIONS_DIR / "break_glass")),
            timeout=Duration.seconds(10),
            reserved_concurrent_executions=5,
            dead_letter_queue=assume_dlq,
        )
        if assume_fn.role is None:
            raise RuntimeError("BreakGlassAssumeFn was not assigned an execution role")

        break_glass_policy = iam.ManagedPolicy(
            self,
            "BreakGlassPolicy",
            description="Full control of Sentinel resources only, for the break-glass role.",
            statements=[
                iam.PolicyStatement(
                    effect=iam.Effect.ALLOW,
                    actions=["bedrock:*", "dynamodb:*", "s3:*", "kms:*"],
                    resources=sentinel_resource_arns,
                )
            ],
        )
        # The 900s break-glass session cap (phase-01 §6) is enforced by the
        # DurationSeconds passed to sts:AssumeRole in assume.py, not here:
        # IAM rejects MaxSessionDuration below 3600s (its hard floor).
        self.break_glass_role = iam.Role(
            self,
            "BreakGlassRole",
            role_name="IAMSentinelBreakGlassRole",
            assumed_by=iam.ArnPrincipal(assume_fn.role.role_arn),
            max_session_duration=Duration.hours(1),
            managed_policies=[break_glass_policy],
        )
        assume_fn.add_to_role_policy(
            iam.PolicyStatement(actions=["sts:AssumeRole"], resources=[self.break_glass_role.role_arn])
        )

        record_first_signer = tasks.LambdaInvoke(
            self, "RecordFirstSigner", lambda_function=approval_fn, payload_response_only=True
        )
        await_second_signer = tasks.LambdaInvoke(
            self, "AwaitSecondSigner", lambda_function=approval_fn, payload_response_only=True
        )
        single_signer_denied = sfn.Fail(
            self,
            "SingleSignerDenied",
            error="AccessDenied",
            cause="break-glass requires two distinct signers within 60 seconds",
        )
        assume_role_and_tag = tasks.LambdaInvoke(
            self,
            "AssumeRoleAndTag",
            lambda_function=assume_fn,
            payload=sfn.TaskInput.from_object(
                {
                    "role_arn": self.break_glass_role.role_arn,
                    "first_principal_id.$": "$.first_principal_id",
                    "second_principal_id.$": "$.second_principal_id",
                }
            ),
            payload_response_only=True,
        )

        definition = record_first_signer.next(await_second_signer).next(
            sfn.Choice(self, "TwoDistinctSignersWithinWindow?")
            .when(sfn.Condition.boolean_equals("$.approved", True), assume_role_and_tag)
            .otherwise(single_signer_denied)
        )

        workflow_log_group = logs.LogGroup(
            self,
            "BreakGlassWorkflowLogs",
            retention=logs.RetentionDays.ONE_YEAR,
            encryption_key=self.data_key,
            removal_policy=RemovalPolicy.RETAIN,
        )
        self.data_key.grant_encrypt_decrypt(
            iam.ServicePrincipal(f"logs.{self.region}.amazonaws.com")
        )
        self.break_glass_workflow = sfn.StateMachine(
            self,
            "BreakGlassWorkflow",
            state_machine_type=sfn.StateMachineType.STANDARD,
            definition_body=sfn.DefinitionBody.from_chainable(definition),
            timeout=Duration.seconds(120),
            tracing_enabled=True,
            logs=sfn.LogOptions(destination=workflow_log_group, level=sfn.LogLevel.ALL),
        )

        self.security_topic = sns.Topic(
            self, "SecurityTopic", topic_name="SentinelSecurity", master_key=self.data_key
        )
        self.data_key.grant_encrypt_decrypt(iam.ServicePrincipal("sns.amazonaws.com"))
        self.security_topic.add_to_resource_policy(
            iam.PolicyStatement(
                sid="EnforceTLS",
                effect=iam.Effect.DENY,
                principals=[iam.AnyPrincipal()],
                actions=["sns:Publish"],
                resources=[self.security_topic.topic_arn],
                conditions={"Bool": {"aws:SecureTransport": "false"}},
            )
        )
        assumption_rule = events.Rule(
            self,
            "BreakGlassAssumptionRule",
            event_pattern=events.EventPattern(
                source=["aws.sts"],
                detail_type=["AWS API Call via CloudTrail"],
                detail={
                    "eventName": ["AssumeRole"],
                    "requestParameters": {"roleArn": [self.break_glass_role.role_arn]},
                },
            ),
        )
        assumption_rule.add_target(targets.SnsTopic(self.security_topic))

        cloudwatch.Alarm(
            self,
            "BreakGlassAssumptionAlarm",
            metric=cloudwatch.Metric(
                namespace="AWS/Events",
                metric_name="Invocations",
                dimensions_map={"RuleName": assumption_rule.rule_name},
                statistic="Sum",
                period=Duration.minutes(5),
            ),
            threshold=1,
            evaluation_periods=1,
            alarm_description="Recent Break-Glass Sessions",
        ).add_alarm_action(cloudwatch_actions.SnsAction(self.security_topic))
