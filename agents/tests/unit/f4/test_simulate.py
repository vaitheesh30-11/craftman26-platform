from __future__ import annotations

import pytest

from iam_sentinel_agents.tools.common.scp_policy_evaluator import LevelPolicies, PolicyRef
from iam_sentinel_agents.tools.f4 import simulate

pytestmark = pytest.mark.unit

_FULL_AWS_ACCESS = PolicyRef(
    arn="arn:aws:organizations::123456789012:policy/o-abc/service_control_policy/p-FullAWSAccess",
    name="FullAWSAccess",
    document={
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow", "Action": "*", "Resource": "*"}],
    },
)

_PROPOSED_DENY_TERMINATE = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "DenyTerminate",
            "Effect": "Deny",
            "Action": "ec2:TerminateInstances",
            "Resource": "*",
        }
    ],
}


def _base_chain() -> list[LevelPolicies]:
    return [
        LevelPolicies(level="root", target="r-abcd", policies=[_FULL_AWS_ACCESS]),
        LevelPolicies(level="account", target="123456789012", policies=[]),
    ]


def test_overlay_proposed_scp_add_mode_keeps_existing_policies() -> None:
    overlaid = simulate.overlay_proposed_scp(_base_chain(), _PROPOSED_DENY_TERMINATE, mode="add")
    assert len(overlaid[-1].policies) == 1
    assert overlaid[-1].policies[0].document == _PROPOSED_DENY_TERMINATE


def test_overlay_proposed_scp_replace_mode_drops_existing_policies() -> None:
    chain = _base_chain()
    chain[-1] = LevelPolicies(level="account", target="123456789012", policies=[_FULL_AWS_ACCESS])
    overlaid = simulate.overlay_proposed_scp(chain, _PROPOSED_DENY_TERMINATE, mode="replace")
    assert len(overlaid[-1].policies) == 1
    assert overlaid[-1].policies[0].name == "ProposedSCP"


def test_overlay_proposed_scp_rejects_an_empty_chain() -> None:
    with pytest.raises(ValueError, match="chain must contain"):
        simulate.overlay_proposed_scp([], _PROPOSED_DENY_TERMINATE)


def test_simulate_blocks_a_regular_role_and_proposes_an_arn_exemption() -> None:
    history = [
        {
            "role_arn": "arn:aws:iam::123456789012:role/AutoScalerCaller",
            "event_source": "ec2.amazonaws.com",
            "event_name": "TerminateInstances",
            "action": "ec2:TerminateInstances",
            "call_count": 400,
        },
        {
            "role_arn": "arn:aws:iam::123456789012:role/Deployer",
            "event_source": "s3.amazonaws.com",
            "event_name": "PutBucketPolicy",
            "action": "s3:PutBucketPolicy",
            "call_count": 5,
        },
    ]
    result = simulate.simulate(
        chain=_base_chain(), proposed_scp=_PROPOSED_DENY_TERMINATE, history=history
    )

    assert result["total_calls_analyzed"] == 405
    assert result["calls_that_would_be_blocked"] == 400
    assert len(result["impacted_roles"]) == 1
    blocked = result["impacted_roles"][0]
    assert blocked.role_arn == "arn:aws:iam::123456789012:role/AutoScalerCaller"
    assert blocked.denying_statement_id == "DenyTerminate"
    assert blocked.denying_level == "account"

    assert len(result["suggested_exemptions"]) == 1
    exemption = result["suggested_exemptions"][0]
    assert (
        exemption.statement_to_add["Condition"]["ArnNotLike"]["aws:PrincipalArn"]
        == blocked.role_arn
    )
    assert exemption.statement_to_add["Sid"] == "DenyTerminate"


def test_simulate_proposes_a_principal_is_aws_service_exemption_for_an_slr() -> None:
    history = [
        {
            "role_arn": (
                "arn:aws:iam::123456789012:role/aws-service-role/"
                "autoscaling.amazonaws.com/AWSServiceRoleForAutoScaling"
            ),
            "event_source": "ec2.amazonaws.com",
            "event_name": "TerminateInstances",
            "action": "ec2:TerminateInstances",
            "call_count": 1200,
        }
    ]
    result = simulate.simulate(
        chain=_base_chain(), proposed_scp=_PROPOSED_DENY_TERMINATE, history=history
    )

    assert len(result["suggested_exemptions"]) == 1
    exemption = result["suggested_exemptions"][0]
    assert exemption.statement_to_add["Condition"]["Bool"] == {"aws:PrincipalIsAWSService": "true"}


def test_simulate_reports_no_blocked_calls_when_nothing_matches() -> None:
    history = [
        {
            "role_arn": "arn:aws:iam::123456789012:role/Reader",
            "event_source": "s3.amazonaws.com",
            "event_name": "GetObject",
            "action": "s3:GetObject",
            "call_count": 50,
        }
    ]
    result = simulate.simulate(
        chain=_base_chain(), proposed_scp=_PROPOSED_DENY_TERMINATE, history=history
    )
    assert result["impacted_roles"] == []
    assert result["suggested_exemptions"] == []
    assert result["calls_that_would_be_blocked"] == 0


def test_build_impact_payload_round_trips_through_the_contract() -> None:
    history = [
        {
            "role_arn": "arn:aws:iam::123456789012:role/AutoScalerCaller",
            "event_source": "ec2.amazonaws.com",
            "event_name": "TerminateInstances",
            "action": "ec2:TerminateInstances",
            "call_count": 400,
        }
    ]
    chain = _base_chain()
    result = simulate.simulate(chain=chain, proposed_scp=_PROPOSED_DENY_TERMINATE, history=history)
    payload = simulate.build_impact_payload(
        proposed_scp_target="123456789012",
        proposed_scp=_PROPOSED_DENY_TERMINATE,
        chain=chain,
        simulation=result,
    )

    assert payload.proposed_scp_target == "123456789012"
    assert payload.calls_that_would_be_blocked == 400
    assert payload.proposed_scp_bytes > 0
    assert len(payload.impacted_roles) == 1
    assert payload.engine_version
