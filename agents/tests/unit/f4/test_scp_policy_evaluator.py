"""Unit coverage for `tools/common/scp_policy_evaluator.py` (phase-05 SS8: "the SCP
evaluation engine tested... against fixture policies covering Allow, Deny,
NotAction, NotResource, Condition (aws:PrincipalIsAWSService), wildcard").
Scaled down from the spec's 30-fixture exhaustive sweep per the revised
testing policy -- one focused case per documented algorithm branch, plus
the monotonic property SS8 calls out as the highest-value check.
"""

from __future__ import annotations

import pytest

from iam_sentinel_agents.tools.common.scp_policy_evaluator import (
    evaluate_action,
    LevelPolicies,
    PolicyRef,
)

pytestmark = pytest.mark.unit

_FULL_AWS_ACCESS = PolicyRef(
    arn="arn:aws:organizations::123456789012:policy/o-abc/service_control_policy/p-FullAWSAccess",
    name="FullAWSAccess",
    document={
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow", "Action": "*", "Resource": "*"}],
    },
)


def _root(*policies: PolicyRef) -> LevelPolicies:
    return LevelPolicies(level="root", target="r-abcd", policies=list(policies))


def _account(*policies: PolicyRef) -> LevelPolicies:
    return LevelPolicies(level="account", target="123456789012", policies=list(policies))


def test_full_aws_access_allows_everything() -> None:
    result = evaluate_action([_root(_FULL_AWS_ACCESS)], "s3:PutBucketPolicy")
    assert result.allowed is True
    assert result.denying_policy_arn is None


def test_explicit_deny_blocks_and_reports_policy_and_statement() -> None:
    deny_policy = PolicyRef(
        arn="arn:aws:organizations::123456789012:policy/o-abc/service_control_policy/p-deny",
        name="DenyTerminate",
        document={
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "DenyTerminate",
                    "Effect": "Deny",
                    "Action": "ec2:TerminateInstances",
                    "Resource": "*",
                }
            ],
        },
    )
    result = evaluate_action(
        [_root(_FULL_AWS_ACCESS), _account(deny_policy)], "ec2:TerminateInstances"
    )
    assert result.allowed is False
    assert result.denying_policy_arn == deny_policy.arn
    assert result.denying_statement_id == "DenyTerminate"
    assert result.denying_level == "account"


def test_not_action_inverts_which_actions_a_deny_covers() -> None:
    # Deny everything EXCEPT s3:GetObject -- s3:GetObject must stay allowed,
    # every other action must be denied.
    deny_policy = PolicyRef(
        arn="arn:aws:organizations::123456789012:policy/o-abc/service_control_policy/p-notaction",
        name="DenyExceptGet",
        document={
            "Version": "2012-10-17",
            "Statement": [{"Effect": "Deny", "NotAction": "s3:GetObject", "Resource": "*"}],
        },
    )
    chain = [_root(_FULL_AWS_ACCESS), _account(deny_policy)]
    assert evaluate_action(chain, "s3:GetObject").allowed is True
    assert evaluate_action(chain, "s3:PutObject").allowed is False


def test_not_resource_inverts_which_resources_a_deny_covers() -> None:
    deny_policy = PolicyRef(
        arn="arn:aws:organizations::123456789012:policy/o-abc/service_control_policy/p-notresource",
        name="DenyExceptSandboxBucket",
        document={
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Deny",
                    "Action": "s3:DeleteObject",
                    "NotResource": "arn:aws:s3:::sandbox-*/*",
                }
            ],
        },
    )
    chain = [_root(_FULL_AWS_ACCESS), _account(deny_policy)]
    assert (
        evaluate_action(
            chain, "s3:DeleteObject", resource="arn:aws:s3:::sandbox-bucket/key"
        ).allowed
        is True
    )
    assert (
        evaluate_action(chain, "s3:DeleteObject", resource="arn:aws:s3:::prod-bucket/key").allowed
        is False
    )


def test_wildcard_action_pattern_matches_case_insensitively() -> None:
    deny_policy = PolicyRef(
        arn="arn:aws:organizations::123456789012:policy/o-abc/service_control_policy/p-wild",
        name="DenyAllIamWrites",
        document={
            "Version": "2012-10-17",
            "Statement": [{"Effect": "Deny", "Action": "IAM:*", "Resource": "*"}],
        },
    )
    chain = [_root(_FULL_AWS_ACCESS), _account(deny_policy)]
    assert evaluate_action(chain, "iam:CreateRole").allowed is False
    assert evaluate_action(chain, "s3:PutObject").allowed is True


def test_conditioned_deny_is_conservatively_applied_for_a_normal_role() -> None:
    deny_policy = PolicyRef(
        arn="arn:aws:organizations::123456789012:policy/o-abc/service_control_policy/p-cond",
        name="DenyIamExceptServices",
        document={
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "DenyIamExceptServices",
                    "Effect": "Deny",
                    "Action": "iam:*",
                    "Resource": "*",
                    "Condition": {"BoolIfExists": {"aws:PrincipalIsAWSService": "false"}},
                }
            ],
        },
    )
    result = evaluate_action(
        [_root(_FULL_AWS_ACCESS), _account(deny_policy)],
        "iam:CreateRole",
        principal_arn="arn:aws:iam::123456789012:role/HumanOperator",
    )
    assert result.allowed is False


def test_principal_is_aws_service_condition_is_resolved_false_for_a_service_linked_role() -> None:
    # phase-05 SS4 Step 2.5's one exactly-resolved condition: a Deny gated on
    # aws:PrincipalIsAWSService=true never fires for a service-*linked
    # role* -- an SLR is an IAM role, not itself an AWS service principal,
    # so this condition is knowably False for it and the Deny cannot apply.
    deny_policy = PolicyRef(
        arn="arn:aws:organizations::123456789012:policy/o-abc/service_control_policy/p-cond",
        name="DenyIamExceptServices",
        document={
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "DenyIamExceptServices",
                    "Effect": "Deny",
                    "Action": "iam:*",
                    "Resource": "*",
                    "Condition": {"Bool": {"aws:PrincipalIsAWSService": "true"}},
                }
            ],
        },
    )
    result = evaluate_action(
        [_root(_FULL_AWS_ACCESS), _account(deny_policy)],
        "iam:CreateRole",
        principal_arn="arn:aws:iam::123456789012:role/aws-service-role/guardduty.amazonaws.com/AWSServiceRoleForAmazonGuardDuty",
    )
    assert result.allowed is True


def test_replacing_full_aws_access_with_a_narrow_allow_list_excludes_uncovered_actions() -> None:
    # No explicit Deny anywhere -- the allow-list ceiling itself excludes
    # anything not in it (phase-05 SS4 Step 2: SCPs are a ceiling, not a grant).
    allow_list = PolicyRef(
        arn="arn:aws:organizations::123456789012:policy/o-abc/service_control_policy/p-allowlist",
        name="ReadOnlyCeiling",
        document={
            "Version": "2012-10-17",
            "Statement": [{"Effect": "Allow", "Action": "s3:Get*", "Resource": "*"}],
        },
    )
    chain = [_root(allow_list)]
    assert evaluate_action(chain, "s3:GetObject").allowed is True
    assert evaluate_action(chain, "s3:PutObject").allowed is False


def test_deny_at_any_level_never_grows_the_effective_allowed_set() -> None:
    """Property (phase-05 SS8): adding a Deny to a chain that was already
    allowed can only turn `allowed` False, never the reverse.
    """
    baseline = evaluate_action([_root(_FULL_AWS_ACCESS)], "ec2:TerminateInstances")
    assert baseline.allowed is True

    deny_policy = PolicyRef(
        arn="arn:aws:organizations::123456789012:policy/o-abc/service_control_policy/p-deny",
        name="DenyTerminate",
        document={
            "Version": "2012-10-17",
            "Statement": [{"Effect": "Deny", "Action": "ec2:TerminateInstances", "Resource": "*"}],
        },
    )
    with_deny = evaluate_action(
        [_root(_FULL_AWS_ACCESS), _account(deny_policy)], "ec2:TerminateInstances"
    )
    assert with_deny.allowed is False
