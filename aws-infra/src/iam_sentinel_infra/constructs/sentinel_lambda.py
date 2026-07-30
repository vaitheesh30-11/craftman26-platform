"""Lambda function wrapper with IAM Sentinel's mandatory runtime defaults
(phase-00 §4, phase-04 §3): Python 3.12/arm64, Powertools, active X-Ray, a
DLQ with 14-day retention, a dedicated least-privilege execution role (no
role reuse across Lambdas -- phase-04 §5), and the two standard alarms
every Sentinel Lambda gets (§2, §6): `Errors > 5 / 5min` and an anomaly-
detection band on `Duration`. No Sentinel Lambda is defined outside this
construct.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aws_cdk import Duration
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_cloudwatch_actions as cloudwatch_actions
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sqs as sqs
from constructs import Construct

if TYPE_CHECKING:
    from iam_sentinel_infra.constructs.sentinel_permission_boundary import (
        SentinelPermissionBoundary,
    )

DEFAULT_MEMORY_MB = 1024
DEFAULT_TIMEOUT = Duration.seconds(300)
DEFAULT_RESERVED_CONCURRENCY = 10
_ERROR_ALARM_THRESHOLD = 5
_ERROR_ALARM_PERIOD = Duration.minutes(5)

# Every `lambda_.Code.from_asset(...)` call site in this repo must pass this:
# pytest imports each `functions/*/handler.py` for its own unit tests, which
# writes `__pycache__/*.pyc` into that same directory. `Code.from_asset`
# hashes the directory's full byte content for its S3 asset key, so an
# uncontrolled pycache write between "capture a snapshot" and "resynth to
# verify it's stable" was making every snapshot depending on a Lambda asset
# non-deterministic (found while verifying aws-infra phase-06's toolchain
# run -- see ADR 0020's sibling fix, not a phase-06-specific resource).
LAMBDA_ASSET_EXCLUDES = ["__pycache__", "*.pyc"]


class SentinelLambda(Construct):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        code: lambda_.Code,
        handler: str,
        stage: str,
        region: str,
        extra_environment: dict[str, str] | None = None,
        powertools_layer: lambda_.ILayerVersion | None = None,
        boto3_layer: lambda_.ILayerVersion | None = None,
        permission_boundary: SentinelPermissionBoundary | None = None,
        role_statements: list[iam.PolicyStatement] | None = None,
        memory_size: int = DEFAULT_MEMORY_MB,
        timeout: Duration | None = None,
        reserved_concurrent_executions: int = DEFAULT_RESERVED_CONCURRENCY,
        log_retention: logs.RetentionDays = logs.RetentionDays.TWO_WEEKS,
        alarm_topic: sns.ITopic | None = None,
    ) -> None:
        super().__init__(scope, construct_id)
        timeout = timeout if timeout is not None else DEFAULT_TIMEOUT

        self.dead_letter_queue = sqs.Queue(
            self,
            "Dlq",
            retention_period=Duration.days(14),
            enforce_ssl=True,
        )

        self.role = iam.Role(
            self,
            "Role",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                )
            ],
        )
        if permission_boundary is not None:
            permission_boundary.apply_to_scope(self)
        for statement in role_statements or []:
            self.role.add_to_policy(statement)

        environment = {
            "SENTINEL_STAGE": stage,
            "SENTINEL_REGION": region,
            "SENTINEL_LOG_LEVEL": "INFO",
            "SENTINEL_METRIC_NAMESPACE": "IAMSentinel",
            "POWERTOOLS_METRICS_NAMESPACE": "IAMSentinel",
            **(extra_environment or {}),
        }

        layers = [layer for layer in (powertools_layer, boto3_layer) if layer is not None]

        self.function = lambda_.Function(
            self,
            "Function",
            code=code,
            handler=handler,
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            memory_size=memory_size,
            timeout=timeout,
            environment=environment,
            layers=layers,
            role=self.role,
            tracing=lambda_.Tracing.ACTIVE,
            reserved_concurrent_executions=reserved_concurrent_executions,
            dead_letter_queue=self.dead_letter_queue,
            log_retention=log_retention,
        )

        self.error_alarm = self._build_error_alarm(alarm_topic)
        self.duration_anomaly_alarm = self._build_duration_anomaly_alarm(alarm_topic)

    def _build_error_alarm(self, alarm_topic: sns.ITopic | None) -> cloudwatch.Alarm:
        """`Errors > 5 / 5min` (phase-04 §2)."""
        alarm = self.function.metric_errors(
            period=_ERROR_ALARM_PERIOD, statistic="sum"
        ).create_alarm(
            self,
            "ErrorAlarm",
            threshold=_ERROR_ALARM_THRESHOLD,
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            alarm_description=f"{self.function.function_name}: more than "
            f"{_ERROR_ALARM_THRESHOLD} errors in 5 minutes.",
        )
        if alarm_topic is not None:
            alarm.add_alarm_action(cloudwatch_actions.SnsAction(alarm_topic))
        return alarm

    def _build_duration_anomaly_alarm(self, alarm_topic: sns.ITopic | None) -> cloudwatch.CfnAlarm:
        """Anomaly-detected `Duration` p95 (phase-04 §2): CloudWatch anomaly
        detection needs a raw metric-math alarm (`ANOMALY_DETECTION_BAND`),
        which the L2 `Metric.create_alarm` API doesn't expose -- hence the
        L1 `CfnAlarm` here instead of `cloudwatch.Alarm`.
        """
        duration_metric_id = "m1"
        band_id = "ad1"
        alarm = cloudwatch.CfnAlarm(
            self,
            "DurationAnomalyAlarm",
            alarm_description=f"{self.function.function_name}: p95 Duration outside its "
            "normal anomaly-detection band.",
            comparison_operator="LessThanLowerOrGreaterThanUpperThreshold",
            evaluation_periods=3,
            threshold_metric_id=band_id,
            treat_missing_data="notBreaching",
            metrics=[
                cloudwatch.CfnAlarm.MetricDataQueryProperty(
                    id=duration_metric_id,
                    metric_stat=cloudwatch.CfnAlarm.MetricStatProperty(
                        metric=cloudwatch.CfnAlarm.MetricProperty(
                            namespace="AWS/Lambda",
                            metric_name="Duration",
                            dimensions=[
                                cloudwatch.CfnAlarm.DimensionProperty(
                                    name="FunctionName", value=self.function.function_name
                                )
                            ],
                        ),
                        period=300,
                        stat="p95",
                    ),
                    return_data=True,
                ),
                cloudwatch.CfnAlarm.MetricDataQueryProperty(
                    id=band_id,
                    expression=f"ANOMALY_DETECTION_BAND({duration_metric_id}, 2)",
                    label=f"{self.function.function_name} Duration (expected)",
                ),
            ],
            alarm_actions=[alarm_topic.topic_arn] if alarm_topic is not None else None,
        )
        return alarm
