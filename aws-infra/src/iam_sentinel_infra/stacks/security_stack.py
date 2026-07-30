"""KMS CMKs, the Sentinel permission boundary, and the Guardrail custom
resource. Populated by aws-infra phase-01; phase-00 only wires the stack
into the app graph.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import aws_cdk as cdk
from aws_cdk import Stack

if TYPE_CHECKING:
    from constructs import Construct

    from iam_sentinel_infra.config import StageConfig


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
