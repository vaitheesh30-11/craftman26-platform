"""Custom resource wrapping `bedrock-agent:AssociateAgentCollaborator`
(phase-05 §6). CloudFormation has no native
`AWS::Bedrock::AgentCollaborator` resource, matching the same gap the
Guardrail lifecycle Lambda (aws-infra phase-01) closes for
`AWS::Bedrock::Guardrail`. See `functions/agent_collaborator/handler.py`
for why every association targets the Supervisor's `DRAFT` version.
"""

from __future__ import annotations

from pathlib import Path

from aws_cdk import CustomResource, Duration
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_sqs as sqs
from constructs import Construct

from iam_sentinel_infra.constructs.sentinel_lambda import LAMBDA_ASSET_EXCLUDES

_FUNCTIONS_DIR = Path(__file__).resolve().parents[3] / "functions"


class AgentCollaboratorAssociation(Construct):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        supervisor_agent_id: str,
        collaborator_name: str,
        collaboration_instruction: str,
        collaborator_alias_arn: str,
        relay_conversation_history: str = "TO_COLLABORATOR",
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
            code=lambda_.Code.from_asset(str(_FUNCTIONS_DIR / "agent_collaborator"), exclude=LAMBDA_ASSET_EXCLUDES),
            timeout=Duration.seconds(60),
            reserved_concurrent_executions=5,
            dead_letter_queue=self.dead_letter_queue,
        )
        self.handler.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock:AssociateAgentCollaborator",
                    "bedrock:UpdateAgentCollaborator",
                    "bedrock:DisassociateAgentCollaborator",
                    "bedrock:GetAgentCollaborator",
                ],
                resources=["*"],  # Collaborator id is not known before AWS assigns it.
            )
        )

        self.resource = CustomResource(
            self,
            "Resource",
            service_token=self.handler.function_arn,
            properties={
                "SupervisorAgentId": supervisor_agent_id,
                "CollaboratorName": collaborator_name,
                "CollaborationInstruction": collaboration_instruction,
                "CollaboratorAliasArn": collaborator_alias_arn,
                "RelayConversationHistory": relay_conversation_history,
            },
        )
