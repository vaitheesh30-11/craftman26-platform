"""API Gateway REST + WebSocket + Cognito authorizer. Populated by
aws-infra phase-07; phase-00 only wires the stack into the app graph and
takes its upstream dependencies for the Lambda and Bedrock Agent targets
it will need once routes land.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import aws_cdk as cdk
from aws_cdk import Stack

if TYPE_CHECKING:
    from constructs import Construct

    from iam_sentinel_infra.config import StageConfig
    from iam_sentinel_infra.stacks.bedrock_stack import BedrockStack
    from iam_sentinel_infra.stacks.lambda_stack import LambdaStack
    from iam_sentinel_infra.stacks.security_stack import SecurityStack


class ApiStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        stage_config: StageConfig,
        lambdas: LambdaStack,
        bedrock: BedrockStack,
        security: SecurityStack,
        env: cdk.Environment | None = None,
    ) -> None:
        super().__init__(scope, construct_id, env=env)
        self.stage_config = stage_config
        self.lambdas = lambdas
        self.bedrock = bedrock
        self.security = security
