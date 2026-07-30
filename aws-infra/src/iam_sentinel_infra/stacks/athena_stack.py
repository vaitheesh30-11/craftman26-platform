"""Glue Data Catalog table + Athena workgroup over CloudTrail logs.
Populated by aws-infra phase-03; phase-00 only wires the stack into the
app graph and takes its `FoundationStack` dependency for the results bucket
it will need once resources land.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import aws_cdk as cdk
from aws_cdk import Stack

if TYPE_CHECKING:
    from constructs import Construct

    from iam_sentinel_infra.config import StageConfig
    from iam_sentinel_infra.stacks.foundation_stack import FoundationStack


class AthenaStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        stage_config: StageConfig,
        foundation: FoundationStack,
        env: cdk.Environment | None = None,
    ) -> None:
        super().__init__(scope, construct_id, env=env)
        self.stage_config = stage_config
        self.foundation = foundation
