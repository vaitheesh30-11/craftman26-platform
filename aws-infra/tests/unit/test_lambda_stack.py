"""Contract checks for the Lambda shared substrate (phase-04 §2, §5, §6).
Per ADR 0011 this stack owns layers + the `new_function()`/
`standard_environment()` factory, not any of the ~25 registry functions
(those land with their owning phases) -- so these tests exercise the
factory itself rather than asserting a fixed function count.
"""

from __future__ import annotations

import aws_cdk as cdk
from aws_cdk import aws_lambda as lambda_
from aws_cdk.assertions import Template

from iam_sentinel_infra.app_factory import build_app
from iam_sentinel_infra.stacks.lambda_stack import LambdaStack


def _lambda_stack() -> tuple[cdk.App, LambdaStack]:
    app = build_app("dev")
    stack = app.node.find_child("SentinelLambda")
    assert isinstance(stack, LambdaStack)
    return app, stack


def _same_env(lambda_stack: LambdaStack) -> cdk.Environment:
    """A downstream owning-phase stack (e.g. F1's own stack) must share
    `LambdaStack`'s account/region -- CDK refuses cross-environment
    references for `new_function()`'s permission-boundary and
    Athena-grant wiring otherwise."""
    return cdk.Environment(
        account=lambda_stack.stage_config.account_id,
        region=lambda_stack.stage_config.region,
    )


def test_two_versioned_layers_are_created_and_exported_by_ssm() -> None:
    _, lambda_stack = _lambda_stack()
    template = Template.from_stack(lambda_stack)
    template.resource_count_is("AWS::Lambda::LayerVersion", 2)
    template.resource_count_is("AWS::SSM::Parameter", 2)


def test_standard_environment_matches_agents_phase_00_contract() -> None:
    _, lambda_stack = _lambda_stack()
    env = lambda_stack.standard_environment()

    assert set(env) == {
        "SENTINEL_STAGE",
        "SENTINEL_FINDINGS_TABLE",
        "SENTINEL_EVIDENCE_BUCKET",
        "SENTINEL_KMS_KEY_ARN",
        "SENTINEL_CROSS_ACCOUNT_ROLE_NAME",
        "SENTINEL_LOG_LEVEL",
        "SENTINEL_METRIC_NAMESPACE",
    }
    assert env["SENTINEL_CROSS_ACCOUNT_ROLE_NAME"] == "SentinelCrossAccountRole"


def test_new_function_creates_dedicated_role_with_boundary_dlq_and_layers() -> None:
    app, lambda_stack = _lambda_stack()
    scratch = cdk.Stack(app, "TestConsumerFn", env=_same_env(lambda_stack))

    fn = lambda_stack.new_function(
        scratch,
        "TestFn",
        code=lambda_.Code.from_inline("def handler(event, context): return {}"),
    )

    assert fn.function.role is not None
    assert fn.dead_letter_queue is not None

    template = Template.from_stack(scratch)
    resources = template.find_resources("AWS::Lambda::Function")
    # CDK auto-adds a singleton `LogRetention` custom-resource Lambda for the
    # `log_retention` property alongside our own function -- filter to ours.
    (function_props,) = (
        r["Properties"] for logical_id, r in resources.items() if logical_id.startswith("TestFn")
    )
    assert len(function_props["Layers"]) == 2


def test_new_function_with_needs_athena_query_grants_athena_access() -> None:
    app, lambda_stack = _lambda_stack()
    scratch = cdk.Stack(app, "TestConsumerAthenaFn", env=_same_env(lambda_stack))

    lambda_stack.new_function(
        scratch,
        "TestAthenaFn",
        code=lambda_.Code.from_inline("def handler(event, context): return {}"),
        needs_athena_query=True,
    )

    template = Template.from_stack(scratch)
    policies = template.find_resources("AWS::IAM::Policy")
    actions = [
        statement["Action"]
        for policy in policies.values()
        for statement in policy["Properties"]["PolicyDocument"]["Statement"]
    ]
    flat_actions = [a for group in actions for a in (group if isinstance(group, list) else [group])]
    assert "athena:StartQueryExecution" in flat_actions
