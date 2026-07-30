"""Sentinel Prime + the 8 specialist Bedrock Agents, the Knowledge Base,
and collaborator associations. Populated by aws-infra phase-05; phase-00
only wires the stack into the app graph and takes its upstream dependencies
for the Lambda action-group targets it will need once agents land.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import aws_cdk as cdk
from aws_cdk import Stack

if TYPE_CHECKING:
    from constructs import Construct

    from iam_sentinel_infra.config import StageConfig
    from iam_sentinel_infra.stacks.foundation_stack import FoundationStack
    from iam_sentinel_infra.stacks.lambda_stack import LambdaStack
    from iam_sentinel_infra.stacks.security_stack import SecurityStack


class BedrockStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        stage_config: StageConfig,
        security: SecurityStack,
        foundation: FoundationStack,
        lambdas: LambdaStack,
        env: cdk.Environment | None = None,
    ) -> None:
        super().__init__(scope, construct_id, env=env)
        self.stage_config = stage_config
        self.security = security
        self.foundation = foundation
        self.lambdas = lambdas
