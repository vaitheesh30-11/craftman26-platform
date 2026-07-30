"""Custom resource closing the `agentCollaboration`/`memoryConfiguration`
gap between `aws-cdk-lib==2.163.0`'s `CfnAgent` L1 and the real Bedrock
`UpdateAgent` API (phase-05 §4/§6; see `sentinel_bedrock_agent.py`'s module
docstring and ADR 0012 for the full explanation).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from aws_cdk import CustomResource, Duration
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_sqs as sqs
from constructs import Construct

from iam_sentinel_infra.constructs.sentinel_lambda import LAMBDA_ASSET_EXCLUDES

_FUNCTIONS_DIR = Path(__file__).resolve().parents[3] / "functions"


class AgentSettingsCustomResource(Construct):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        agent_id: str,
        agent_name: str,
        agent_resource_role_arn: str,
        foundation_model: str,
        instruction: str,
        agent_collaboration: str | None = None,
        memory_configuration: dict[str, Any] | None = None,
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
            code=lambda_.Code.from_asset(str(_FUNCTIONS_DIR / "agent_settings"), exclude=LAMBDA_ASSET_EXCLUDES),
            timeout=Duration.seconds(60),
            reserved_concurrent_executions=5,
            dead_letter_queue=self.dead_letter_queue,
        )
        self.handler.add_to_role_policy(
            iam.PolicyStatement(
                actions=["bedrock:UpdateAgent"],
                resources=["*"],  # Agent ARN is not resolvable before CfnAgent creates it.
            )
        )
        # UpdateAgent re-validates agentResourceRoleArn's trust policy on
        # every call, which requires the caller to be able to pass it.
        self.handler.add_to_role_policy(
            iam.PolicyStatement(
                actions=["iam:PassRole"],
                resources=[agent_resource_role_arn],
                conditions={"StringEquals": {"iam:PassedToService": "bedrock.amazonaws.com"}},
            )
        )

        properties: dict[str, Any] = {
            "AgentId": agent_id,
            "AgentName": agent_name,
            "AgentResourceRoleArn": agent_resource_role_arn,
            "FoundationModel": foundation_model,
            "Instruction": instruction,
        }
        if agent_collaboration is not None:
            properties["AgentCollaboration"] = agent_collaboration
        if memory_configuration is not None:
            properties["MemoryConfiguration"] = memory_configuration

        self.resource = CustomResource(
            self, "Resource", service_token=self.handler.function_arn, properties=properties
        )
