"""Managed policy applied as a permission boundary to every Sentinel role
(phase-00 §4, phase-01 §5). No Sentinel-created role can escalate outside
Sentinel's own resources or mutate IAM/Organizations/CloudFormation beyond
its narrow, explicitly-scoped exceptions — even if its own attached
policies are later widened.
"""

from __future__ import annotations

from aws_cdk import aws_iam as iam
from constructs import Construct

_F5_SESSION_TERMINATOR_ROLE_PATH = "aws-reserved/sso.amazonaws.com/*"


class SentinelPermissionBoundary(Construct):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        resource_prefix_arns: list[str],
    ) -> None:
        super().__init__(scope, construct_id)

        self.policy = iam.ManagedPolicy(
            self,
            "Boundary",
            description="Permission boundary for every IAM Sentinel role.",
            statements=[
                iam.PolicyStatement(
                    sid="AllowWithinSentinelResources",
                    effect=iam.Effect.ALLOW,
                    actions=[
                        "bedrock:*",
                        "dynamodb:*",
                        "s3:*",
                        "kms:*",
                        "access-analyzer:*",
                        "organizations:Describe*",
                        "organizations:List*",
                    ],
                    resources=resource_prefix_arns,
                ),
                iam.PolicyStatement(
                    # Both role names are fixed literals owned by aws-infra
                    # phase-08 (`crossaccount_stack.CROSS_ACCOUNT_ROLE_NAME` /
                    # `DELEGATED_ADMIN_ROLE_NAME`) -- not imported here to avoid
                    # a stack-ordering dependency this construct doesn't
                    # otherwise need.
                    sid="AllowCrossAccountRoleAssumption",
                    effect=iam.Effect.ALLOW,
                    actions=["sts:AssumeRole"],
                    resources=[
                        "arn:aws:iam::*:role/SentinelCrossAccountRole",
                        "arn:aws:iam::*:role/SentinelDelegatedAdminAccountRole",
                    ],
                ),
                iam.PolicyStatement(
                    sid="AllowF5SessionTerminatorScope",
                    effect=iam.Effect.ALLOW,
                    actions=["iam:PutRolePolicy", "iam:DeleteRolePolicy"],
                    resources=[f"arn:aws:iam::*:role/{_F5_SESSION_TERMINATOR_ROLE_PATH}"],
                ),
                iam.PolicyStatement(
                    sid="DenyIamMutationOutsideF5Scope",
                    effect=iam.Effect.DENY,
                    actions=["iam:Create*", "iam:Delete*", "iam:Attach*Policy*"],
                    not_resources=[f"arn:aws:iam::*:role/{_F5_SESSION_TERMINATOR_ROLE_PATH}"],
                ),
                iam.PolicyStatement(
                    sid="DenyOrganizationsWrites",
                    effect=iam.Effect.DENY,
                    actions=["organizations:Update*", "organizations:Delete*"],
                    resources=["*"],
                ),
                iam.PolicyStatement(
                    sid="DenySelfMutationViaCloudFormation",
                    effect=iam.Effect.DENY,
                    actions=["cloudformation:*"],
                    resources=["*"],
                ),
                iam.PolicyStatement(
                    sid="DenyBoundaryEscalation",
                    effect=iam.Effect.DENY,
                    actions=[
                        "iam:CreatePolicyVersion",
                        "iam:DeleteRolePermissionsBoundary",
                        "iam:PutRolePermissionsBoundary",
                    ],
                    resources=["*"],
                    conditions={
                        "StringNotEquals": {
                            "iam:PermissionsBoundary": "SentinelPermissionBoundary"
                        }
                    },
                ),
            ],
        )

    def apply_to_scope(self, scope: Construct) -> None:
        """Apply as the permissions boundary for every role created under `scope`."""
        iam.PermissionsBoundary.of(scope).apply(self.policy)
