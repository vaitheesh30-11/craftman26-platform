"""Every Sentinel tool Lambda + the shared Powertools/boto3 layers.
Populated by aws-infra phase-04; phase-00 only wires the stack into the app
graph and takes its upstream dependencies for the resources its Lambdas
will need once they land.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import aws_cdk as cdk
from aws_cdk import Stack

if TYPE_CHECKING:
    from constructs import Construct

    from iam_sentinel_infra.config import StageConfig
    from iam_sentinel_infra.stacks.athena_stack import AthenaStack
    from iam_sentinel_infra.stacks.foundation_stack import FoundationStack
    from iam_sentinel_infra.stacks.security_stack import SecurityStack


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
