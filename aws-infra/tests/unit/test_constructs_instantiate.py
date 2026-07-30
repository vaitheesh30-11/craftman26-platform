"""Every shared L3 construct must be importable and instantiable from a
plain stack with no circular refs (aws-infra README §8 acceptance)."""

from __future__ import annotations

from aws_cdk import App, Stack
from aws_cdk import aws_kms as kms
from aws_cdk import aws_lambda as lambda_
from aws_cdk.assertions import Template

from iam_sentinel_infra.constructs.guardrail_custom_resource import GuardrailCustomResource
from iam_sentinel_infra.constructs.sentinel_bedrock_agent import SentinelBedrockAgent
from iam_sentinel_infra.constructs.sentinel_lambda import SentinelLambda
from iam_sentinel_infra.constructs.sentinel_permission_boundary import SentinelPermissionBoundary
from iam_sentinel_infra.constructs.signed_object_lock_bucket import SignedObjectLockBucket


def _stack() -> Stack:
    return Stack(App(), "TestStack")


def test_signed_object_lock_bucket_instantiates() -> None:
    stack = _stack()
    key = kms.Key(stack, "Key")

    construct = SignedObjectLockBucket(stack, "Evidence", kms_key=key)

    assert construct.bucket.bucket_name is not None


def test_sentinel_lambda_instantiates() -> None:
    stack = _stack()

    construct = SentinelLambda(
        stack,
        "Fn",
        code=lambda_.Code.from_inline("def handler(event, context): return {}"),
        handler="index.handler",
        stage="dev",
        region="us-east-1",
    )

    assert construct.function.runtime.name == lambda_.Runtime.PYTHON_3_12.name
    Template.from_stack(stack).has_resource_properties(
        "AWS::Lambda::Function", {"MemorySize": 1024, "Timeout": 300}
    )


def test_sentinel_lambda_gets_own_role_with_boundary_and_alarms() -> None:
    stack = _stack()
    boundary = SentinelPermissionBoundary(
        stack, "Boundary", resource_prefix_arns=["arn:aws:s3:::sentinel-*"]
    )

    fn_a = SentinelLambda(
        stack,
        "FnA",
        code=lambda_.Code.from_inline("def handler(event, context): return {}"),
        handler="index.handler",
        stage="dev",
        region="us-east-1",
        permission_boundary=boundary,
    )
    fn_b = SentinelLambda(
        stack,
        "FnB",
        code=lambda_.Code.from_inline("def handler(event, context): return {}"),
        handler="index.handler",
        stage="dev",
        region="us-east-1",
        permission_boundary=boundary,
    )

    assert fn_a.role.role_arn != fn_b.role.role_arn
    assert fn_a.error_alarm.alarm_arn is not None
    assert fn_a.duration_anomaly_alarm.ref is not None


def test_sentinel_bedrock_agent_instantiates() -> None:
    stack = _stack()

    construct = SentinelBedrockAgent(
        stack,
        "Prime",
        agent_name="SentinelPrime",
        foundation_model="anthropic.claude-3-5-sonnet-20241022-v2:0",
        instruction="You are Sentinel Prime.",
    )

    assert set(construct.aliases) == {"dev", "staging", "prod"}


def test_guardrail_custom_resource_instantiates() -> None:
    stack = _stack()

    construct = GuardrailCustomResource(
        stack,
        "Guardrail",
        guardrail_name="SentinelGuardrail",
        blocked_input_messaging="blocked",
        blocked_outputs_messaging="blocked",
    )

    assert construct.resource.node.id == "Resource"


def test_sentinel_permission_boundary_applies_to_scope() -> None:
    stack = _stack()
    construct = SentinelPermissionBoundary(
        stack, "Boundary", resource_prefix_arns=["arn:aws:iam::111111111111:role/Sentinel*"]
    )

    construct.apply_to_scope(stack)

    assert construct.policy.managed_policy_arn is not None
