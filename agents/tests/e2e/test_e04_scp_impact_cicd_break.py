"""E-04 — Proposed SCP breaks CI/CD role (phase-13 scenario table). Real
`tools/f4/simulate.simulate` (pure computation, no AWS calls -- see that
module's own docstring) overlaying a proposed deny-all SCP onto a chain
that a CI/CD deployment role has been calling heavily. Passes when: impact
report lists the CI/CD role, severity=CRITICAL (per `tools/f4/severity.
assign_severity`'s call-count rubric).
"""

from __future__ import annotations

from iam_sentinel_agents.tools.common.scp_policy_evaluator import LevelPolicies, PolicyRef
from iam_sentinel_agents.tools.f4.severity import assign_severity
from iam_sentinel_agents.tools.f4.simulate import build_impact_payload, simulate

_CICD_ROLE_ARN = "arn:aws:iam::123456789012:role/CiCdDeployer"
_ROOT_ALLOW = PolicyRef(
    arn="arn:aws:organizations::o-abc:policy/service_control_policy/p-fullaccess",
    name="FullAWSAccess",
    document={"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "*", "Resource": "*"}]},
)
_CHAIN = [LevelPolicies(level="root", target="r-root", policies=[_ROOT_ALLOW])]
_PROPOSED_SCP = {
    "Version": "2012-10-17",
    "Statement": [{"Effect": "Deny", "Action": "cloudformation:*", "Resource": "*"}],
}
_HISTORY = [
    {
        "role_arn": _CICD_ROLE_ARN,
        "event_source": "cloudformation.amazonaws.com",
        "event_name": "UpdateStack",
        "call_count": 1500,
    },
    {
        "role_arn": "arn:aws:iam::123456789012:role/ReadOnlyAuditor",
        "event_source": "s3.amazonaws.com",
        "event_name": "GetObject",
        "call_count": 3,
    },
]


def test_e04_proposed_scp_breaks_cicd_role_with_critical_severity() -> None:
    result = simulate(chain=_CHAIN, proposed_scp=_PROPOSED_SCP, history=_HISTORY)

    impacted_roles = {b.role_arn: b for b in result["impacted_roles"]}
    assert _CICD_ROLE_ARN in impacted_roles
    cicd_impact = impacted_roles[_CICD_ROLE_ARN]
    assert cicd_impact.call_count_last_90_days == 1500

    severity = assign_severity(cicd_impact.call_count_last_90_days, is_production_account=True)
    assert severity == "CRITICAL"

    payload = build_impact_payload(
        proposed_scp_target="r-root",
        proposed_scp=_PROPOSED_SCP,
        chain=_CHAIN,
        simulation=result,
    )
    assert payload.calls_that_would_be_blocked >= 1500
    # The read-only auditor's 3 calls are a different service (`s3`), never
    # touched by the proposed `cloudformation:*` deny -- not impacted.
    assert "arn:aws:iam::123456789012:role/ReadOnlyAuditor" not in impacted_roles
