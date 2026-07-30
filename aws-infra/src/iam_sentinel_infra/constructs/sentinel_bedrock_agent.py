"""Bedrock Agent wrapper: foundation model, Guardrail wiring, per-stage
aliases, Knowledge Base attachment, and an OpenAPI action-group builder
(phase-00 §4). Populated by aws-infra phase-05.

`aws-cdk-lib==2.163.0`'s `CfnAgent` L1 predates two GA fields the real
`CreateAgent`/`UpdateAgent` APIs already support (confirmed via
`boto3==1.35.36`'s service model): `agentCollaboration` and
`memoryConfiguration`. `AgentSettingsCustomResource` closes that gap with a
post-create `UpdateAgent` call -- see phase-05 §10's own risk note ("Multi-
agent collaboration API surface changes; still evolving") and ADR 0012.

See ADR 0012 for why Sentinel Prime and the 8 specialists are not
*instantiated* through this construct yet -- their instruction prompts and
action-group OpenAPI specs are owned by agents phase-01 and the Wave-6
specialist phases, none of which have landed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from aws_cdk import aws_bedrock as bedrock
from constructs import Construct

from iam_sentinel_infra.constructs.agent_settings_custom_resource import (
    AgentSettingsCustomResource,
)

_ALIASES = ("dev", "staging", "prod")


def build_action_group(
    *, name: str, openapi_path: str | Path, executor_lambda_arn: str
) -> bedrock.CfnAgent.AgentActionGroupProperty:
    """Reads an OpenAPI YAML file (`agents/src/iam_sentinel_agents/action_groups/*.yaml`,
    owned by the specialist phase that defines the tool surface) and wires
    it to the Lambda that executes it (phase-05 §5).
    """
    openapi_schema = yaml.safe_load(Path(openapi_path).read_text(encoding="utf-8"))
    return bedrock.CfnAgent.AgentActionGroupProperty(
        action_group_name=name,
        action_group_executor=bedrock.CfnAgent.ActionGroupExecutorProperty(
            lambda_=executor_lambda_arn
        ),
        api_schema=bedrock.CfnAgent.APISchemaProperty(payload=yaml.dump(openapi_schema)),
    )


class SentinelBedrockAgent(Construct):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        agent_name: str,
        foundation_model: str,
        instruction: str,
        agent_resource_role_arn: str | None = None,
        guardrail_identifier: str | None = None,
        guardrail_version: str | None = None,
        action_groups: list[bedrock.CfnAgent.AgentActionGroupProperty] | None = None,
        knowledge_bases: list[bedrock.CfnAgent.AgentKnowledgeBaseProperty] | None = None,
        agent_collaboration: str | None = None,
        memory_configuration: dict[str, Any] | None = None,
        idle_session_ttl_in_seconds: int = 1800,
    ) -> None:
        super().__init__(scope, construct_id)

        guardrail_configuration = None
        if guardrail_identifier is not None:
            guardrail_configuration = bedrock.CfnAgent.GuardrailConfigurationProperty(
                guardrail_identifier=guardrail_identifier,
                guardrail_version=guardrail_version,
            )

        self.agent = bedrock.CfnAgent(
            self,
            "Agent",
            agent_name=agent_name,
            agent_resource_role_arn=agent_resource_role_arn,
            foundation_model=foundation_model,
            instruction=instruction,
            guardrail_configuration=guardrail_configuration,
            action_groups=action_groups or [],
            knowledge_bases=knowledge_bases,
            idle_session_ttl_in_seconds=idle_session_ttl_in_seconds,
            auto_prepare=True,
        )

        self.settings: AgentSettingsCustomResource | None = None
        if agent_collaboration is not None or memory_configuration is not None:
            if agent_resource_role_arn is None:
                raise ValueError(
                    "agent_collaboration/memory_configuration require an explicit "
                    "agent_resource_role_arn: UpdateAgent is a full-replace API and "
                    "cannot recover CFN's auto-generated service-role ARN."
                )
            self.settings = AgentSettingsCustomResource(
                self,
                "Settings",
                agent_id=self.agent.attr_agent_id,
                agent_name=agent_name,
                agent_resource_role_arn=agent_resource_role_arn,
                foundation_model=foundation_model,
                instruction=instruction,
                agent_collaboration=agent_collaboration,
                memory_configuration=memory_configuration,
            )
            self.settings.node.add_dependency(self.agent)

        self.aliases = {
            name: bedrock.CfnAgentAlias(
                self,
                f"Alias{name.capitalize()}",
                agent_id=self.agent.attr_agent_id,
                agent_alias_name=name,
            )
            for name in _ALIASES
        }
        if self.settings is not None:
            for alias in self.aliases.values():
                alias.node.add_dependency(self.settings)
