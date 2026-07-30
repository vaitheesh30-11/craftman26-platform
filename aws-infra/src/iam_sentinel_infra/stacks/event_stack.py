"""EventBridge rules, scheduled expressions, and CloudWatch alarms.
Populated by aws-infra phase-06; phase-00 only wires the stack into the app
graph and takes its upstream dependencies for the Lambda targets and DDB
tables it will need once rules land.
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


class EventStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        stage_config: StageConfig,
        lambdas: LambdaStack,
        foundation: FoundationStack,
        env: cdk.Environment | None = None,
    ) -> None:
        super().__init__(scope, construct_id, env=env)
        self.stage_config = stage_config
        self.lambdas = lambdas
        self.foundation = foundation
