"""aws-infra phase-05: Knowledge Base resources + the `new_agent()`/
`associate_collaborator()` substrate (ADR 0012). No specialist prompt or
action-group YAML exists yet, so these tests exercise the factory with
inline synthetic content rather than any real agents/ artifact.
"""

from __future__ import annotations

import aws_cdk as cdk
from aws_cdk.assertions import Template

from iam_sentinel_infra.app_factory import build_app
from iam_sentinel_infra.config import load_stage_config
from iam_sentinel_infra.stacks.athena_stack import AthenaStack
from iam_sentinel_infra.stacks.bedrock_stack import BedrockStack
from iam_sentinel_infra.stacks.foundation_stack import FoundationStack
from iam_sentinel_infra.stacks.lambda_stack import LambdaStack
from iam_sentinel_infra.stacks.security_stack import SecurityStack


def _bedrock_stack() -> BedrockStack:
    app = cdk.App()
    stage_config = load_stage_config("dev")
    env = cdk.Environment(account=stage_config.account_id, region=stage_config.region)
    security = SecurityStack(app, "SentinelSecurity", stage_config=stage_config, env=env)
    foundation = FoundationStack(
        app, "SentinelFoundation", stage_config=stage_config, security=security, env=env
    )
    athena = AthenaStack(app, "SentinelAthena", stage_config=stage_config, foundation=foundation, env=env)
    lambdas = LambdaStack(
        app,
        "SentinelLambda",
        stage_config=stage_config,
        security=security,
        foundation=foundation,
        athena=athena,
        env=env,
    )
    return BedrockStack(
        app,
        "SentinelBedrock",
        stage_config=stage_config,
        security=security,
        foundation=foundation,
        lambdas=lambdas,
        env=env,
    )


def test_knowledge_base_and_four_data_sources_present() -> None:
    stack = _bedrock_stack()
    template = Template.from_stack(stack)

    template.resource_count_is("AWS::Bedrock::KnowledgeBase", 1)
    template.resource_count_is("AWS::Bedrock::DataSource", 4)
    template.has_resource_properties(
        "AWS::Bedrock::KnowledgeBase",
        {"KnowledgeBaseConfiguration": {"Type": "VECTOR"}},
    )


def test_knowledge_base_reuses_foundation_kb_source_bucket_not_a_new_bucket() -> None:
    stack = _bedrock_stack()
    template = Template.from_stack(stack)

    # ADR 0012: the spec's pseudocode names a fresh `SentinelKbSource-{stage}`
    # bucket, but FoundationStack (phase-02) already provisioned
    # `kb_source_bucket` for this exact consumer -- BedrockStack must not
    # create a second one.
    template.resource_count_is("AWS::S3::Bucket", 0)


def test_new_agent_wires_guardrail_and_kb_and_publishes_alias_ssm() -> None:
    stack = _bedrock_stack()

    agent = stack.new_agent(
        stack,
        "TestAgent",
        agent_name="SentinelTestAgent",
        foundation_model="anthropic.claude-3-5-haiku-20241022-v1:0",
        instruction="You are a test agent.",
    )

    template = Template.from_stack(stack)
    assert set(agent.aliases) == {"dev", "staging", "prod"}
    template.has_resource_properties(
        "AWS::Bedrock::Agent",
        {"KnowledgeBases": [{"KnowledgeBaseState": "ENABLED"}]},
    )
    template.resource_count_is("AWS::SSM::Parameter", 3 + 1)  # 3 aliases + KbIdParam


def test_new_agent_with_collaboration_requires_settings_custom_resource() -> None:
    stack = _bedrock_stack()

    stack.new_agent(
        stack,
        "TestSupervisor",
        agent_name="SentinelTestSupervisor",
        foundation_model="anthropic.claude-3-5-sonnet-20241022-v2:0",
        instruction="You are a test supervisor.",
        agent_collaboration="SUPERVISOR",
        memory_configuration={"enabledMemoryTypes": ["SESSION_SUMMARY"], "storageDays": 30},
    )

    template = Template.from_stack(stack)
    template.resource_count_is("AWS::CloudFormation::CustomResource", 2)  # KB index bootstrap + settings


def test_associate_collaborator_creates_custom_resource() -> None:
    stack = _bedrock_stack()
    supervisor = stack.new_agent(
        stack,
        "Supervisor",
        agent_name="SentinelSupervisor",
        foundation_model="anthropic.claude-3-5-sonnet-20241022-v2:0",
        instruction="Supervisor.",
    )
    specialist = stack.new_agent(
        stack,
        "Specialist",
        agent_name="SentinelSpecialist",
        foundation_model="anthropic.claude-3-5-haiku-20241022-v1:0",
        instruction="Specialist.",
    )

    stack.associate_collaborator(
        stack,
        "SupervisorToSpecialist",
        supervisor=supervisor,
        collaborator=specialist,
        collaborator_name="Specialist",
        collaboration_instruction="Delegate to Specialist for X.",
    )

    template = Template.from_stack(stack)
    template.resource_count_is("AWS::CloudFormation::CustomResource", 2)  # KB index bootstrap + association


def test_full_app_graph_still_synthesizes_with_bedrock_populated() -> None:
    app = build_app("dev")
    assembly = app.synth()
    assert "SentinelBedrock" in {artifact.id for artifact in assembly.stacks}
