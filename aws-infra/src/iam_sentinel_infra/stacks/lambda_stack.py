"""Shared Lambda substrate for every Sentinel tool Lambda (phase-04): the
two versioned layers (`SentinelPowertoolsLayer`, `SentinelBoto3Layer`), the
standard environment contract every Lambda expects at cold start
(`agents/docs/phase-00-foundations.txt` §3.3), and `new_function()` -- the
one place every owning phase calls to get a `SentinelLambda` wired to its
own least-privilege role (permission boundary applied, no role reuse),
DLQ, and the two standard alarms.

Per ADR 0011, this stack does NOT instantiate any of the ~25 registry
functions in `aws-infra/docs/phase-04-lambda-stack.txt` §4 -- every one of
them is attributed to a specific *future* phase in that table's own "Owned
by phase" column (agents phase-01 through phase-17, none of which have
landed yet). Each owning phase calls `LambdaStack.new_function()` from its
own stack when it lands, the same way `AthenaStack.grant_query_access()`
(phase-03) is called by this stack rather than by phase-03 itself.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import aws_cdk as cdk
from aws_cdk import Duration, Stack
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_sns as sns
from aws_cdk import aws_ssm as ssm
from cdk_nag import NagSuppressions

from iam_sentinel_infra.constructs.sentinel_lambda import (
    DEFAULT_MEMORY_MB,
    DEFAULT_RESERVED_CONCURRENCY,
    DEFAULT_TIMEOUT,
    SentinelLambda,
)

if TYPE_CHECKING:
    from constructs import Construct

    from iam_sentinel_infra.config import StageConfig
    from iam_sentinel_infra.stacks.athena_stack import AthenaStack
    from iam_sentinel_infra.stacks.foundation_stack import FoundationStack
    from iam_sentinel_infra.stacks.security_stack import SecurityStack

_LAYERS_DIR = Path(__file__).resolve().parents[3] / "functions" / "layers"

# Cross-account role name is a fixed literal across the whole platform, not
# a per-stack resource this stack owns -- see docs/ARCHITECTURE.md §5 and
# `SentinelPermissionBoundary`'s `AllowCrossAccountRoleAssumption` statement.
SENTINEL_CROSS_ACCOUNT_ROLE_NAME = "SentinelCrossAccountRole"


class LambdaStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        stage_config: StageConfig,
        security: SecurityStack,
        foundation: FoundationStack,
        athena: AthenaStack,
        env: cdk.Environment | None = None,
    ) -> None:
        super().__init__(scope, construct_id, env=env)
        self.stage_config = stage_config
        self.security = security
        self.foundation = foundation
        self.athena = athena

        self.powertools_layer = self._build_layer(
            "PowertoolsLayer",
            asset_dir=_LAYERS_DIR / "powertools",
            description="aws-lambda-powertools + pydantic v2, built via CodeBuild at CI "
            "time per phase-04 §6 -- see ADR 0011.",
            ssm_name="powertools",
        )
        self.boto3_layer = self._build_layer(
            "Boto3Layer",
            asset_dir=_LAYERS_DIR / "boto3",
            description="Latest patched boto3, rebuilt monthly per phase-04 §6 -- see "
            "ADR 0011.",
            ssm_name="boto3",
        )

        NagSuppressions.add_stack_suppressions(
            self,
            [
                {
                    "id": "AwsSolutions-IAM4",
                    "reason": (
                        "AWSLambdaBasicExecutionRole is CDK's default Lambda execution "
                        "role addition (CloudWatch Logs only, scoped to the function's "
                        "own log group)."
                    ),
                    "appliesTo": [
                        "Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
                    ],
                },
                {
                    "id": "HIPAA.Security-LambdaInsideVPC",
                    "reason": (
                        "docs/ARCHITECTURE.md §Networking: IAM Sentinel is deliberately "
                        "VPC-less across the whole platform."
                    ),
                },
            ],
        )

    def _build_layer(
        self, construct_id: str, *, asset_dir: Path, description: str, ssm_name: str
    ) -> lambda_.LayerVersion:
        layer = lambda_.LayerVersion(
            self,
            construct_id,
            code=lambda_.Code.from_asset(str(asset_dir)),
            compatible_runtimes=[lambda_.Runtime.PYTHON_3_12],
            compatible_architectures=[lambda_.Architecture.ARM_64],
            description=description,
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )
        ssm.StringParameter(
            self,
            f"{construct_id}ArnParam",
            parameter_name=f"/sentinel/{self.stage_config.stage}/layers/{ssm_name}/arn",
            string_value=layer.layer_version_arn,
        )
        return layer

    def standard_environment(self) -> dict[str, str]:
        """The env vars every Sentinel Lambda expects at cold start
        (`agents/docs/phase-00-foundations.txt` §3.3). Callers merge
        per-Lambda specifics on top via `new_function(extra_environment=...)`.
        """
        return {
            "SENTINEL_STAGE": self.stage_config.stage,
            "SENTINEL_FINDINGS_TABLE": self.foundation.tables["SentinelFindings"].table_name,
            "SENTINEL_EVIDENCE_BUCKET": self.foundation.evidence_bucket.bucket_name,
            "SENTINEL_KMS_KEY_ARN": self.security.evidence_key.key_arn,
            "SENTINEL_CROSS_ACCOUNT_ROLE_NAME": SENTINEL_CROSS_ACCOUNT_ROLE_NAME,
            "SENTINEL_LOG_LEVEL": "INFO",
            "SENTINEL_METRIC_NAMESPACE": "IAMSentinel",
        }

    def new_function(
        self,
        scope: Construct,
        construct_id: str,
        *,
        code: lambda_.Code,
        handler: str = "handler.handler",
        role_statements: list[iam.PolicyStatement] | None = None,
        extra_environment: dict[str, str] | None = None,
        memory_size: int = DEFAULT_MEMORY_MB,
        timeout: Duration = DEFAULT_TIMEOUT,
        reserved_concurrent_executions: int = DEFAULT_RESERVED_CONCURRENCY,
        log_retention: logs.RetentionDays = logs.RetentionDays.TWO_WEEKS,
        alarm_topic: sns.ITopic | None = None,
        needs_athena_query: bool = False,
        needs_athena_write: bool = False,
    ) -> SentinelLambda:
        """The one entry point every owning phase (agents phase-01..17)
        calls to register its Lambda -- own role + permission boundary +
        DLQ + alarms + the shared layers + the standard environment, per
        phase-04 §5-6. `scope` is the *caller's own stack* (e.g. F1's
        stack), not `LambdaStack` itself -- functions live where their
        owning phase defines them; this stack only owns the shared
        substrate. See the module docstring and ADR 0011.
        """
        merged_environment = {**self.standard_environment(), **(extra_environment or {})}

        fn = SentinelLambda(
            scope,
            construct_id,
            code=code,
            handler=handler,
            stage=self.stage_config.stage,
            region=self.stage_config.region,
            extra_environment=merged_environment,
            powertools_layer=self.powertools_layer,
            boto3_layer=self.boto3_layer,
            permission_boundary=self.security.permission_boundary,
            role_statements=role_statements,
            memory_size=memory_size,
            timeout=timeout,
            reserved_concurrent_executions=reserved_concurrent_executions,
            log_retention=log_retention,
            alarm_topic=alarm_topic,
        )

        if needs_athena_query or needs_athena_write:
            self.athena.grant_query_access(fn.role, write=needs_athena_write)

        return fn
