"""Custom resource owning the Bedrock Guardrail lifecycle (phase-00 §4).

CloudFormation has no native `AWS::Bedrock::Guardrail` resource as of this
writing, so create/update/delete is driven by a Lambda-backed custom
resource calling `bedrock:CreateGuardrail` / `UpdateGuardrail` /
`DeleteGuardrail` / `CreateGuardrailVersion` directly.
"""

from __future__ import annotations

from aws_cdk import CustomResource, Duration
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from constructs import Construct


class GuardrailCustomResource(Construct):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        guardrail_name: str,
        blocked_input_messaging: str,
        blocked_outputs_messaging: str,
    ) -> None:
        super().__init__(scope, construct_id)

        self.handler = lambda_.Function(
            self,
            "Handler",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            handler="index.handler",
            code=lambda_.Code.from_inline(
                "def handler(event, context):\n"
                "    raise NotImplementedError('wired in agents phase-11')\n"
            ),
            timeout=Duration.seconds(60),
        )
        self.handler.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock:CreateGuardrail",
                    "bedrock:UpdateGuardrail",
                    "bedrock:DeleteGuardrail",
                    "bedrock:CreateGuardrailVersion",
                    "bedrock:GetGuardrail",
                ],
                resources=["*"],  # Guardrail ARN is not known before creation.
            )
        )

        self.resource = CustomResource(
            self,
            "Resource",
            service_token=self.handler.function_arn,
            properties={
                "GuardrailName": guardrail_name,
                "BlockedInputMessaging": blocked_input_messaging,
                "BlockedOutputsMessaging": blocked_outputs_messaging,
            },
        )
