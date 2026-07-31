"""scp_impact_simulate -- phase-05 SS4 Steps 4-5: overlay the proposed SCP
onto the walked chain and predict which historical write calls would now be
denied. Step 6's severity rubric lives in `tools/f4/severity.py` -- it is
applied by the specialist prompt when building Findings, not by this tool
(see that module's docstring for why).
"""

from __future__ import annotations

import json
from typing import Any, TYPE_CHECKING

from iam_sentinel_agents.contracts.scp_impact import (
    BlockedInvocation,
    ScpImpactPayload,
    SuggestedExemption,
)
from iam_sentinel_agents.tools.common.runtime import sentinel_handler
from iam_sentinel_agents.tools.common.scp_policy_evaluator import (
    ENGINE_VERSION,
    evaluate_action,
    iter_statements,
    LevelPolicies,
    PolicyRef,
)
from iam_sentinel_agents.tools.common.service_prefixes import canonicalize_action

if TYPE_CHECKING:
    from aws_lambda_powertools.utilities.typing import LambdaContext

    from iam_sentinel_agents.tools.common.event_parser import ParsedInvocation

_PROPOSED_POLICY_ARN = "arn:aws:organizations::proposed:policy/service_control_policy/PROPOSED"
_SLR_ARN_MARKER = "/aws-service-role/"


def overlay_proposed_scp(
    chain: list[LevelPolicies], proposed_scp: dict[str, Any], *, mode: str = "add"
) -> list[LevelPolicies]:
    """Insert `proposed_scp` at the target level -- the last entry in
    `chain`, per how `walk_ou.walk_chain` orders root -> ... -> target.
    `mode` mirrors the `/simulate` OpenAPI parameter: `"replace"` swaps out
    every policy currently attached at the target level; `"add"` (default)
    appends alongside them.
    """
    if not chain:
        raise ValueError("chain must contain at least the target level")
    proposed_ref = PolicyRef(arn=_PROPOSED_POLICY_ARN, name="ProposedSCP", document=proposed_scp)
    target_level = chain[-1]
    new_policies = [proposed_ref] if mode == "replace" else [*target_level.policies, proposed_ref]
    return [
        *chain[:-1],
        LevelPolicies(level=target_level.level, target=target_level.target, policies=new_policies),
    ]


def _find_denying_statement(
    chain: list[LevelPolicies], policy_arn: str | None, statement_id: str | None
) -> dict[str, Any] | None:
    if policy_arn is None:
        return None
    for level in chain:
        for policy in level.policies:
            if policy.arn != policy_arn:
                continue
            for statement in iter_statements(policy.document):
                if statement_id is not None:
                    if statement.get("Sid") == statement_id:
                        return statement
                elif statement.get("Effect") == "Deny":
                    return statement
    return None


def _is_slr(role_arn: str) -> bool:
    return _SLR_ARN_MARKER in role_arn


def _build_exemption(
    *,
    chain: list[LevelPolicies],
    role_arn: str,
    policy_arn: str | None,
    statement_id: str | None,
    event_source: str,
    call_count: int,
) -> SuggestedExemption:
    """phase-05 SS4 Step 5: group blocked calls by (role, denying
    statement) and propose a diff-ready statement -- the original denying
    statement (or a minimal reconstruction if it can't be located, e.g. the
    proposed SCP's own allow-list gap rather than an explicit Deny) plus one
    additional exemption Condition.
    """
    base_statement = _find_denying_statement(chain, policy_arn, statement_id) or {
        "Effect": "Deny",
        "Action": ["*"],
        "Resource": "*",
    }
    statement_to_add = dict(base_statement)
    existing_condition = statement_to_add.get("Condition")
    condition = dict(existing_condition) if isinstance(existing_condition, dict) else {}

    if _is_slr(role_arn):
        # Per phase-05 SS4 Step 5 and the engine's own exact resolution of
        # this one condition (tools/common/scp_policy_evaluator._condition_suppresses_
        # deny): `aws:PrincipalIsAWSService=true` is knowably False for any
        # IAM role, including an SLR, so gating the denying statement on it
        # means the statement can never match this caller again -- unlike
        # `BoolIfExists: {...: "false"}`, which would match (and thus still
        # deny) the SLR, since an SLR is *also* not "true" -- that inverted
        # form is the exact SLR-breakage misconfiguration F8 targets.
        condition["Bool"] = {"aws:PrincipalIsAWSService": "true"}
        rationale = (
            f"{role_arn} is a service-linked role invoked {call_count} times in the last 90 days; "
            "gate the denying statement on aws:PrincipalIsAWSService=true so it can never match "
            "this caller (phase-05 SS4 Step 5's SLR exemption path)."
        )
    else:
        condition["ArnNotLike"] = {"aws:PrincipalArn": role_arn}
        rationale = (
            f"{role_arn} made {call_count} of the now-blocked calls in the last 90 days; add an "
            "ArnNotLike exemption on aws:PrincipalArn to the denying statement to preserve its "
            "existing access."
        )
    statement_to_add["Condition"] = condition

    return SuggestedExemption(
        statement_to_add=statement_to_add,
        rationale=rationale,
        references_service=event_source or None,
    )


def simulate(
    *,
    chain: list[LevelPolicies],
    proposed_scp: dict[str, Any],
    history: list[dict[str, Any]],
    mode: str = "add",
) -> dict[str, Any]:
    overlaid = overlay_proposed_scp(chain, proposed_scp, mode=mode)
    blocked: list[BlockedInvocation] = []
    total_calls_analyzed = 0

    for row in history:
        call_count = int(row.get("call_count", 0))
        total_calls_analyzed += call_count
        action = row.get("action") or canonicalize_action(row["event_source"], row["event_name"])
        result = evaluate_action(overlaid, action, principal_arn=row.get("role_arn"))
        if result.allowed:
            continue
        blocked.append(
            BlockedInvocation(
                role_arn=row["role_arn"],
                action=action,
                event_source=row.get("event_source") or action.split(":")[0],
                call_count_last_90_days=call_count,
                denying_scp_arn=result.denying_policy_arn or _PROPOSED_POLICY_ARN,
                denying_statement_id=result.denying_statement_id,
                denying_level=result.denying_level or overlaid[-1].level,
            )
        )

    grouped_counts: dict[tuple[str, str | None], int] = {}
    grouped_meta: dict[tuple[str, str | None], tuple[str | None, str]] = {}
    for invocation in blocked:
        key = (invocation.role_arn, invocation.denying_statement_id)
        grouped_counts[key] = grouped_counts.get(key, 0) + invocation.call_count_last_90_days
        grouped_meta[key] = (invocation.denying_scp_arn, invocation.event_source)

    exemptions = [
        _build_exemption(
            chain=overlaid,
            role_arn=role_arn,
            policy_arn=grouped_meta[key][0],
            statement_id=statement_id,
            event_source=grouped_meta[key][1],
            call_count=call_count,
        )
        for key, call_count in grouped_counts.items()
        for role_arn, statement_id in (key,)
    ]

    return {
        "impacted_roles": blocked,
        "suggested_exemptions": exemptions,
        "total_calls_analyzed": total_calls_analyzed,
        "calls_that_would_be_blocked": sum(b.call_count_last_90_days for b in blocked),
        "chain": overlaid,
    }


def build_impact_payload(
    *,
    proposed_scp_target: str,
    proposed_scp: dict[str, Any],
    chain: list[LevelPolicies],
    simulation: dict[str, Any],
) -> ScpImpactPayload:
    proposed_scp_bytes = len(json.dumps(proposed_scp, separators=(",", ":")).encode("utf-8"))
    return ScpImpactPayload(
        proposed_scp_target=proposed_scp_target,
        proposed_scp=proposed_scp,
        proposed_scp_bytes=proposed_scp_bytes,
        total_calls_analyzed=simulation["total_calls_analyzed"],
        calls_that_would_be_blocked=simulation["calls_that_would_be_blocked"],
        impacted_roles=simulation["impacted_roles"],
        suggested_exemptions=simulation["suggested_exemptions"],
        scp_chain=[level.model_dump(mode="json") for level in chain],
        engine_version=ENGINE_VERSION,
    )


@sentinel_handler(feature_id="F4", tool_name="scp_impact_simulate")
def scp_impact_simulate(invocation: ParsedInvocation, _context: LambdaContext) -> dict[str, Any]:
    chain = [LevelPolicies.model_validate(raw) for raw in invocation.parameters["chain"]]
    proposed_scp = invocation.parameters["proposed_scp"]
    history = list(invocation.parameters.get("history", []))
    mode = invocation.parameters.get("mode", "add")

    result = simulate(chain=chain, proposed_scp=proposed_scp, history=history, mode=mode)
    target = chain[-1].target if chain else ""
    payload = build_impact_payload(
        proposed_scp_target=target, proposed_scp=proposed_scp, chain=chain, simulation=result
    )
    return payload.model_dump(mode="json")
