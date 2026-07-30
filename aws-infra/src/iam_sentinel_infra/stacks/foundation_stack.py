"""DDB tables, S3 evidence/report buckets, SQS FIFO queues, SNS topics.
Populated by aws-infra phase-02; phase-00 only wires the stack into the
app graph and takes its `SecurityStack` dependency for the KMS CMK it will
need once resources land.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import aws_cdk as cdk
from aws_cdk import Stack

if TYPE_CHECKING:
    from constructs import Construct

    from iam_sentinel_infra.config import StageConfig
    from iam_sentinel_infra.stacks.security_stack import SecurityStack


class FoundationStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        stage_config: StageConfig,
        security: SecurityStack,
        env: cdk.Environment | None = None,
    ) -> None:
        super().__init__(scope, construct_id, env=env)
        self.stage_config = stage_config
        self.security = security
