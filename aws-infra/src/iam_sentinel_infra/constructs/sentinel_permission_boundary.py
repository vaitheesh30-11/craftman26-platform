"""Managed policy applied as a permission boundary to every Sentinel role
(phase-00 §4). No Sentinel-created role can escalate outside Sentinel's own
resources, even if its inline/attached policies are later widened.
"""

from __future__ import annotations

from aws_cdk import aws_iam as iam
from constructs import Construct


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
                    actions=["*"],
                    resources=resource_prefix_arns,
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
