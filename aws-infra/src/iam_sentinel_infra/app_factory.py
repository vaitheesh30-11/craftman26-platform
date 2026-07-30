"""Builds the 8-stack app graph in strict deploy order (phase-00 §6).

Separated from `app.py` so tests can build the graph and inspect it without
triggering `App.synth()`.
"""

from __future__ import annotations

import aws_cdk as cdk
from aws_cdk import Tags

from iam_sentinel_infra.config import Stage, load_stage_config
from iam_sentinel_infra.stacks.api_stack import ApiStack
from iam_sentinel_infra.stacks.athena_stack import AthenaStack
from iam_sentinel_infra.stacks.bedrock_stack import BedrockStack
from iam_sentinel_infra.stacks.crossaccount_stack import CrossAccountStack
from iam_sentinel_infra.stacks.event_stack import EventStack
from iam_sentinel_infra.stacks.foundation_stack import FoundationStack
from iam_sentinel_infra.stacks.lambda_stack import LambdaStack
from iam_sentinel_infra.stacks.security_stack import SecurityStack


def build_app(stage: Stage, *, app: cdk.App | None = None) -> cdk.App:
    app = app if app is not None else cdk.App()
    stage_config = load_stage_config(stage)
    env = cdk.Environment(account=stage_config.account_id, region=stage_config.region)

    security = SecurityStack(app, "SentinelSecurity", stage_config=stage_config, env=env)
    foundation = FoundationStack(
        app, "SentinelFoundation", stage_config=stage_config, security=security, env=env
    )
    athena = AthenaStack(
        app, "SentinelAthena", stage_config=stage_config, foundation=foundation, env=env
    )
    lambdas = LambdaStack(
        app,
        "SentinelLambda",
        stage_config=stage_config,
        security=security,
        foundation=foundation,
        athena=athena,
        env=env,
    )
    bedrock = BedrockStack(
        app,
        "SentinelBedrock",
        stage_config=stage_config,
        security=security,
        foundation=foundation,
        lambdas=lambdas,
        env=env,
    )
    event = EventStack(
        app,
        "SentinelEvent",
        stage_config=stage_config,
        lambdas=lambdas,
        foundation=foundation,
        env=env,
    )
    api = ApiStack(
        app,
        "SentinelApi",
        stage_config=stage_config,
        lambdas=lambdas,
        bedrock=bedrock,
        security=security,
        foundation=foundation,
        env=env,
    )
    crossaccount = CrossAccountStack(
        app,
        "SentinelCrossAccount",
        stage_config=stage_config,
        security=security,
        lambdas=lambdas,
        env=env,
    )

    for stack in (security, foundation, athena, lambdas, bedrock, event, api, crossaccount):
        Tags.of(stack).add("Project", "IAMSentinel")
        Tags.of(stack).add("Stage", stage_config.stage)
        Tags.of(stack).add("Owner", "iam-sentinel@customer.com")

    return app
