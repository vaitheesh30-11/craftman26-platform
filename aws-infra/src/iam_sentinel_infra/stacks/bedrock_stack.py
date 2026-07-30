"""Sentinel Prime + the 8 specialist Bedrock Agents, the Knowledge Base,
and collaborator associations (phase-05). Per ADR 0012, this phase builds
the Knowledge Base (§3 -- fully independent of any specialist prompt or
action group) and the reusable agent substrate (`new_agent()`,
`associate_collaborator()`, analogous to `LambdaStack.new_function()` from
ADR 0011), but does NOT instantiate Sentinel Prime or the 8 specialists
themselves: their instruction prompts (`agents/src/iam_sentinel_agents/prompts/`)
and action-group OpenAPI specs (`agents/src/iam_sentinel_agents/action_groups/`)
are owned by agents phase-01 (Wave 3) and the Wave-6 specialist phases, none
of which have landed yet.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import aws_cdk as cdk
from aws_cdk import CustomResource, Duration, Stack
from aws_cdk import aws_bedrock as bedrock
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_opensearchserverless as oss
from aws_cdk import aws_sqs as sqs
from aws_cdk import aws_ssm as ssm
from cdk_nag import NagSuppressions

from iam_sentinel_infra.constructs.agent_collaborator_association import (
    AgentCollaboratorAssociation,
)
from iam_sentinel_infra.constructs.sentinel_bedrock_agent import SentinelBedrockAgent

if TYPE_CHECKING:
    from constructs import Construct

    from iam_sentinel_infra.config import StageConfig
    from iam_sentinel_infra.stacks.foundation_stack import FoundationStack
    from iam_sentinel_infra.stacks.lambda_stack import LambdaStack
    from iam_sentinel_infra.stacks.security_stack import SecurityStack

_FUNCTIONS_DIR = Path(__file__).resolve().parents[3] / "functions"
_KB_COLLECTION_NAME = "sentinel-kb-vector"
_KB_VECTOR_INDEX_NAME = "bedrock-knowledge-base-default-index"
_KB_VECTOR_FIELD = "bedrock-knowledge-base-default-vector"
_KB_TEXT_FIELD = "AMAZON_BEDROCK_TEXT_CHUNK"
_KB_METADATA_FIELD = "AMAZON_BEDROCK_METADATA"
_KB_EMBEDDING_DIMENSIONS = 256
_CHUNK_MAX_TOKENS = 512
_CHUNK_OVERLAP_PERCENTAGE = 20

# phase-05 §3: one data source per AWS corpus, all under
# `foundation.kb_source_bucket` (built ahead of this phase in aws-infra
# phase-02, anticipating this exact consumer).
_KB_CORPORA: tuple[tuple[str, str], ...] = (
    ("IamUserGuide", "iam-user-guide/"),
    ("OrgUserGuide", "organizations-user-guide/"),
    ("IdcUserGuide", "identity-center-user-guide/"),
    ("ServiceAuthorizationReference", "service-authorization-reference/"),
)


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

        self._build_knowledge_base()

        NagSuppressions.add_stack_suppressions(
            self,
            [
                {
                    "id": "AwsSolutions-IAM4",
                    "reason": (
                        "AWSLambdaBasicExecutionRole is CDK's default Lambda execution "
                        "role addition (CloudWatch Logs only, scoped to the function's "
                        "own log group)."
                    ),
                    "appliesTo": [
                        "Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
                    ],
                },
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": (
                        "Guardrail/Collaborator/Agent-settings custom-resource Lambdas call "
                        "bedrock-agent APIs (AssociateAgentCollaborator, UpdateAgent, "
                        "GetAgentCollaborator) whose resource identifiers do not exist "
                        "before AWS assigns them at call time -- the same shape of "
                        "necessary wildcard already justified for "
                        "SecurityStack's GuardrailCustomResource (aws-infra phase-01)."
                    ),
                },
                {
                    "id": "HIPAA.Security-LambdaInsideVPC",
                    "reason": (
                        "docs/ARCHITECTURE.md §Networking: IAM Sentinel is deliberately "
                        "VPC-less across the whole platform."
                    ),
                },
                {
                    "id": "HIPAA.Security-IAMNoInlinePolicy",
                    "reason": (
                        "CDK's auto-generated DefaultPolicy grants (aoss:APIAccessAll "
                        "scoped to the KB's own collection ARN, s3:GetObject/ListBucket "
                        "scoped to the KB source bucket); splitting these into managed "
                        "policies adds indirection with no security benefit, matching "
                        "the FoundationStack precedent (aws-infra phase-02)."
                    ),
                },
            ],
        )

    # ------------------------------------------------------------------
    # Knowledge Base (phase-05 §3) -- buildable now, independent of any
    # specialist prompt. Real live-ingestion verification is deferred; see
    # ADR 0012.
    # ------------------------------------------------------------------
    def _build_knowledge_base(self) -> None:
        self._build_kb_opensearch_collection()
        self._build_kb_role()

        self.knowledge_base = bedrock.CfnKnowledgeBase(
            self,
            "SentinelKB",
            name=f"SentinelKB-{self.stage_config.stage}",
            role_arn=self.kb_role.role_arn,
            knowledge_base_configuration=bedrock.CfnKnowledgeBase.KnowledgeBaseConfigurationProperty(
                type="VECTOR",
                vector_knowledge_base_configuration=bedrock.CfnKnowledgeBase.VectorKnowledgeBaseConfigurationProperty(
                    embedding_model_arn=(
                        f"arn:{self.partition}:bedrock:{self.region}::foundation-model/"
                        f"{self.stage_config.kb_embedding_model_id}"
                    ),
                    embedding_model_configuration=bedrock.CfnKnowledgeBase.EmbeddingModelConfigurationProperty(
                        bedrock_embedding_model_configuration=bedrock.CfnKnowledgeBase.BedrockEmbeddingModelConfigurationProperty(
                            dimensions=_KB_EMBEDDING_DIMENSIONS
                        )
                    ),
                ),
            ),
            storage_configuration=bedrock.CfnKnowledgeBase.StorageConfigurationProperty(
                type="OPENSEARCH_SERVERLESS",
                opensearch_serverless_configuration=bedrock.CfnKnowledgeBase.OpenSearchServerlessConfigurationProperty(
                    collection_arn=self.kb_collection.attr_arn,
                    vector_index_name=_KB_VECTOR_INDEX_NAME,
                    field_mapping=bedrock.CfnKnowledgeBase.OpenSearchServerlessFieldMappingProperty(
                        vector_field=_KB_VECTOR_FIELD,
                        text_field=_KB_TEXT_FIELD,
                        metadata_field=_KB_METADATA_FIELD,
                    ),
                ),
            ),
        )
        self.knowledge_base.node.add_dependency(self.kb_index_bootstrap)

        self.data_sources = {
            logical_id: bedrock.CfnDataSource(
                self,
                f"KbDataSource{logical_id}",
                name=f"SentinelKB-{logical_id}-{self.stage_config.stage}",
                knowledge_base_id=self.knowledge_base.attr_knowledge_base_id,
                data_source_configuration=bedrock.CfnDataSource.DataSourceConfigurationProperty(
                    type="S3",
                    s3_configuration=bedrock.CfnDataSource.S3DataSourceConfigurationProperty(
                        bucket_arn=self.foundation.kb_source_bucket.bucket_arn,
                        inclusion_prefixes=[prefix],
                    ),
                ),
                vector_ingestion_configuration=bedrock.CfnDataSource.VectorIngestionConfigurationProperty(
                    chunking_configuration=bedrock.CfnDataSource.ChunkingConfigurationProperty(
                        chunking_strategy="FIXED_SIZE",
                        fixed_size_chunking_configuration=bedrock.CfnDataSource.FixedSizeChunkingConfigurationProperty(
                            max_tokens=_CHUNK_MAX_TOKENS,
                            overlap_percentage=_CHUNK_OVERLAP_PERCENTAGE,
                        ),
                    ),
                ),
            )
            for logical_id, prefix in _KB_CORPORA
        }

        ssm.StringParameter(
            self,
            "KbIdParam",
            parameter_name=f"/sentinel/{self.stage_config.stage}/kb/id",
            string_value=self.knowledge_base.attr_knowledge_base_id,
        )

    def _build_kb_opensearch_collection(self) -> None:
        encryption_policy = oss.CfnSecurityPolicy(
            self,
            "KbOssEncryptionPolicy",
            name=f"{_KB_COLLECTION_NAME}-enc-{self.stage_config.stage}"[:32],
            type="encryption",
            policy=self.to_json_string(
                {
                    "Rules": [{"ResourceType": "collection", "Resource": [f"collection/{_KB_COLLECTION_NAME}"]}],
                    "AWSOwnedKey": False,
                    "KmsARN": self.security.kb_key.key_arn,
                }
            ),
        )
        network_policy = oss.CfnSecurityPolicy(
            self,
            "KbOssNetworkPolicy",
            name=f"{_KB_COLLECTION_NAME}-net-{self.stage_config.stage}"[:32],
            type="network",
            policy=self.to_json_string(
                [
                    {
                        "Rules": [{"ResourceType": "collection", "Resource": [f"collection/{_KB_COLLECTION_NAME}"]}],
                        "AllowFromPublic": True,
                    }
                ]
            ),
        )

        self.kb_collection = oss.CfnCollection(
            self, "KbVectorCollection", name=_KB_COLLECTION_NAME, type="VECTORSEARCH"
        )
        self.kb_collection.add_dependency(encryption_policy)
        self.kb_collection.add_dependency(network_policy)

        self._build_kb_index_bootstrap()

        access_policy = oss.CfnAccessPolicy(
            self,
            "KbOssAccessPolicy",
            name=f"{_KB_COLLECTION_NAME}-access-{self.stage_config.stage}"[:32],
            type="data",
            policy=self.to_json_string(
                [
                    {
                        "Rules": [
                            {
                                "ResourceType": "collection",
                                "Resource": [f"collection/{_KB_COLLECTION_NAME}"],
                                "Permission": ["aoss:*"],
                            },
                            {
                                "ResourceType": "index",
                                "Resource": [f"index/{_KB_COLLECTION_NAME}/*"],
                                "Permission": ["aoss:*"],
                            },
                        ],
                        # The KB ingestion role and the index-bootstrap Lambda's
                        # own role both need data-plane access; the KB service
                        # role's ARN isn't known until `_build_kb_role` below.
                        "Principal": [
                            f"arn:{self.partition}:iam::{self.stage_config.account_id}:root"
                        ],
                    }
                ]
            ),
        )
        access_policy.node.add_dependency(self.kb_collection)

    def _build_kb_index_bootstrap(self) -> None:
        dead_letter_queue = sqs.Queue(
            self, "KbIndexBootstrapDlq", retention_period=Duration.days(14), enforce_ssl=True
        )
        bootstrap_fn = lambda_.Function(
            self,
            "KbIndexBootstrapFn",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            handler="handler.handler",
            code=lambda_.Code.from_asset(str(_FUNCTIONS_DIR / "kb_index_bootstrap")),
            timeout=Duration.seconds(60),
            reserved_concurrent_executions=2,
            dead_letter_queue=dead_letter_queue,
        )
        bootstrap_fn.add_to_role_policy(
            iam.PolicyStatement(actions=["aoss:APIAccessAll"], resources=[self.kb_collection.attr_arn])
        )

        self.kb_index_bootstrap = CustomResource(
            self,
            "KbIndexBootstrap",
            service_token=bootstrap_fn.function_arn,
            properties={"CollectionEndpoint": self.kb_collection.attr_collection_endpoint},
        )

    def _build_kb_role(self) -> None:
        self.kb_role = iam.Role(
            self,
            "KbRole",
            assumed_by=iam.ServicePrincipal(
                "bedrock.amazonaws.com",
                conditions={
                    "StringEquals": {"aws:SourceAccount": self.stage_config.account_id},
                    "ArnLike": {
                        "aws:SourceArn": (
                            f"arn:{self.partition}:bedrock:{self.region}:"
                            f"{self.stage_config.account_id}:knowledge-base/*"
                        )
                    },
                },
            ),
        )
        self.kb_role.add_to_policy(
            iam.PolicyStatement(
                actions=["s3:GetObject", "s3:ListBucket"],
                resources=[
                    self.foundation.kb_source_bucket.bucket_arn,
                    f"{self.foundation.kb_source_bucket.bucket_arn}/*",
                ],
            )
        )
        self.kb_role.add_to_policy(
            iam.PolicyStatement(actions=["kms:Decrypt"], resources=[self.security.data_key.key_arn])
        )
        self.kb_role.add_to_policy(
            iam.PolicyStatement(actions=["aoss:APIAccessAll"], resources=[self.kb_collection.attr_arn])
        )
        self.kb_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel"],
                resources=[
                    f"arn:{self.partition}:bedrock:{self.region}::foundation-model/"
                    f"{self.stage_config.kb_embedding_model_id}"
                ],
            )
        )

    # ------------------------------------------------------------------
    # Agent substrate (phase-05 §4-§7) -- the factory every owning phase
    # (agents phase-01 Supervisor, the Wave-6 specialist phases) calls
    # once its instruction/action-group content exists. See ADR 0012.
    # ------------------------------------------------------------------
    def new_agent(
        self,
        scope: Construct,
        construct_id: str,
        *,
        agent_name: str,
        foundation_model: str,
        instruction: str,
        role_statements: list[iam.PolicyStatement] | None = None,
        action_groups: list[bedrock.CfnAgent.AgentActionGroupProperty] | None = None,
        attach_knowledge_base: bool = True,
        agent_collaboration: str | None = None,
        memory_configuration: dict[str, Any] | None = None,
        idle_session_ttl_in_seconds: int = 1800,
    ) -> SentinelBedrockAgent:
        """Wires the Guardrail (LIVE version, per SecurityStack) and the
        Knowledge Base onto a new agent, and creates its own least-
        privilege execution role -- the same "own role, no reuse" pattern
        `LambdaStack.new_function()` established for tool Lambdas (ADR
        0011). `scope` is the *caller's own stack*, matching that
        precedent exactly.
        """
        role = iam.Role(
            scope,
            f"{construct_id}Role",
            assumed_by=iam.ServicePrincipal(
                "bedrock.amazonaws.com",
                conditions={
                    "StringEquals": {"aws:SourceAccount": self.stage_config.account_id},
                    "ArnLike": {
                        "aws:SourceArn": (
                            f"arn:{Stack.of(scope).partition}:bedrock:"
                            f"{Stack.of(scope).region}:{self.stage_config.account_id}:agent/*"
                        )
                    },
                },
            ),
        )
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel"],
                resources=[
                    f"arn:{Stack.of(scope).partition}:bedrock:{Stack.of(scope).region}::"
                    f"foundation-model/{foundation_model}"
                ],
            )
        )
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock:ApplyGuardrail"],
                resources=[self.security.guardrail.resource.get_att_string("GuardrailArn")],
            )
        )
        if attach_knowledge_base:
            role.add_to_policy(
                iam.PolicyStatement(
                    actions=["bedrock:Retrieve", "bedrock:RetrieveAndGenerate"],
                    resources=[self.knowledge_base.attr_knowledge_base_arn],
                )
            )
        for statement in role_statements or []:
            role.add_to_policy(statement)

        knowledge_bases = None
        if attach_knowledge_base:
            knowledge_bases = [
                bedrock.CfnAgent.AgentKnowledgeBaseProperty(
                    description="SentinelKB: IAM/Organizations/Identity Center user guides + SAR.",
                    knowledge_base_id=self.knowledge_base.attr_knowledge_base_id,
                    knowledge_base_state="ENABLED",
                )
            ]

        agent = SentinelBedrockAgent(
            scope,
            construct_id,
            agent_name=agent_name,
            foundation_model=foundation_model,
            instruction=instruction,
            agent_resource_role_arn=role.role_arn,
            guardrail_identifier=self.security.guardrail.resource.ref,
            guardrail_version=self.security.guardrail.resource.get_att_string("GuardrailVersion"),
            action_groups=action_groups,
            knowledge_bases=knowledge_bases,
            agent_collaboration=agent_collaboration,
            memory_configuration=memory_configuration,
            idle_session_ttl_in_seconds=idle_session_ttl_in_seconds,
        )

        for alias_name, alias in agent.aliases.items():
            ssm.StringParameter(
                scope,
                f"{construct_id}Alias{alias_name.capitalize()}Param",
                parameter_name=f"/sentinel/agents/{agent_name}/alias/{alias_name}",
                string_value=alias.attr_agent_alias_arn,
            )

        return agent

    def associate_collaborator(
        self,
        scope: Construct,
        construct_id: str,
        *,
        supervisor: SentinelBedrockAgent,
        collaborator: SentinelBedrockAgent,
        collaborator_name: str,
        collaboration_instruction: str,
        relay_conversation_history: str = "TO_COLLABORATOR",
    ) -> AgentCollaboratorAssociation:
        """Wires Prime -> one specialist (phase-05 §6). Called once per
        specialist by whichever phase creates Prime (agents phase-01),
        after every specialist it wants to collaborate with already
        exists -- there is no ordering constraint enforced here beyond
        CDK's own construct-dependency graph.
        """
        association = AgentCollaboratorAssociation(
            scope,
            construct_id,
            supervisor_agent_id=supervisor.agent.attr_agent_id,
            collaborator_name=collaborator_name,
            collaboration_instruction=collaboration_instruction,
            collaborator_alias_arn=collaborator.aliases["dev"].attr_agent_alias_arn,
            relay_conversation_history=relay_conversation_history,
        )
        association.node.add_dependency(collaborator.agent)
        return association
