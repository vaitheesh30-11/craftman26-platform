"""Bedrock Agent wrapper: foundation model, Guardrail wiring, per-stage
aliases, and an OpenAPI action-group builder (phase-00 §4). Populated by
aws-infra phase-05; phase-00 only needs the construct to be importable and
instantiable with an empty action-group list.
"""

from __future__ import annotations

from aws_cdk import aws_bedrock as bedrock
from constructs import Construct

_ALIASES = ("dev", "staging", "prod")


class SentinelBedrockAgent(Construct):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        agent_name: str,
        foundation_model: str,
        instruction: str,
        guardrail_identifier: str | None = None,
        guardrail_version: str | None = None,
        action_groups: list[bedrock.CfnAgent.AgentActionGroupProperty] | None = None,
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
            foundation_model=foundation_model,
            instruction=instruction,
            guardrail_configuration=guardrail_configuration,
            action_groups=action_groups or [],
            auto_prepare=True,
        )

        self.aliases = {
            name: bedrock.CfnAgentAlias(
                self,
                f"Alias{name.capitalize()}",
                agent_id=self.agent.attr_agent_id,
                agent_alias_name=name,
            )
            for name in _ALIASES
        }
