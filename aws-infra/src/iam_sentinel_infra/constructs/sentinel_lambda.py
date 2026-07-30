"""Lambda function wrapper with IAM Sentinel's mandatory runtime defaults
(phase-00 §4): Python 3.12, arm64, Powertools, active X-Ray, a DLQ, and a
14-day log retention floor. No Sentinel Lambda is defined outside this
construct.
"""

from __future__ import annotations

from aws_cdk import Duration
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_sqs as sqs
from constructs import Construct


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
        memory_size: int = 512,
        timeout: Duration | None = None,
        reserved_concurrent_executions: int = 10,
    ) -> None:
        super().__init__(scope, construct_id)
        timeout = timeout if timeout is not None else Duration.seconds(30)

        self.dead_letter_queue = sqs.Queue(
            self,
            "Dlq",
            retention_period=Duration.days(14),
            enforce_ssl=True,
        )

        environment = {
            "SENTINEL_STAGE": stage,
            "SENTINEL_REGION": region,
            "SENTINEL_LOG_LEVEL": "INFO",
            "POWERTOOLS_METRICS_NAMESPACE": "IAMSentinel",
            **(extra_environment or {}),
        }

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
            layers=[powertools_layer] if powertools_layer is not None else [],
            tracing=lambda_.Tracing.ACTIVE,
            reserved_concurrent_executions=reserved_concurrent_executions,
            dead_letter_queue=self.dead_letter_queue,
            log_retention=logs.RetentionDays.TWO_WEEKS,
        )
