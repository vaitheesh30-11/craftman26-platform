"""Custom resource owning the Bedrock Guardrail lifecycle (phase-00 §4,
agents phase-11 §3).

CloudFormation has no native `AWS::Bedrock::Guardrail` resource as of this
writing, so create/update/delete is driven by a Lambda-backed custom
resource calling `bedrock:CreateGuardrail` / `UpdateGuardrail` /
`DeleteGuardrail` / `CreateGuardrailVersion` directly. `policy_config`
carries the topic/content/PII/grounding policy content (agents phase-11
§3) straight through to those calls as a JSON-serializable dict — see
ADR 0004 for why that content lives in `aws-infra/config/guardrail_v1.json`
rather than in the agents package.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from aws_cdk import CustomResource, Duration
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_sqs as sqs
from constructs import Construct

_FUNCTIONS_DIR = Path(__file__).resolve().parents[3] / "functions"


class GuardrailCustomResource(Construct):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        guardrail_name: str,
        blocked_input_messaging: str,
        blocked_outputs_messaging: str,
        policy_config: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(scope, construct_id)

        self.dead_letter_queue = sqs.Queue(
            self, "HandlerDlq", retention_period=Duration.days(14), enforce_ssl=True
        )
        self.handler = lambda_.Function(
            self,
            "Handler",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            handler="handler.handler",
            code=lambda_.Code.from_asset(str(_FUNCTIONS_DIR / "guardrail_lifecycle")),
            timeout=Duration.seconds(60),
            reserved_concurrent_executions=5,
            dead_letter_queue=self.dead_letter_queue,
        )
        self.handler.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock:CreateGuardrail",
                    "bedrock:UpdateGuardrail",
                    "bedrock:DeleteGuardrail",
                    "bedrock:CreateGuardrailVersion",
                    "bedrock:GetGuardrail",
                    "bedrock:ListGuardrails",
                ],
                resources=["*"],  # Guardrail ARN is not known before creation.
            )
        )

        properties: dict[str, Any] = {
            "GuardrailName": guardrail_name,
            "BlockedInputMessaging": blocked_input_messaging,
            "BlockedOutputsMessaging": blocked_outputs_messaging,
        }
        if policy_config is not None:
            properties["PolicyConfig"] = policy_config

        self.resource = CustomResource(
            self, "Resource", service_token=self.handler.function_arn, properties=properties
        )
