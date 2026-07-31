"""Shared SCP evaluation engine.

agents/docs/phase-07-shadow-guard.txt §4 Step 2 calls this module
`scp_engine` and expects `evaluate_action(chain, action)` to already exist,
crediting it to "phase-05" (`agents/docs/phase-05-scp-impact-analyst.txt`
§4 Step 2, which specifies this exact function signature and algorithm).
Phase-05 (F4 SCP Impact Analyst) has not been built yet -- only agents
phase-00 (foundation) and phase-02 (F1 PassRole Cartographer) exist on
`main` as of this phase. Building F6 without an evaluation engine is not an
option (§4 Step 2 is F6's entire ingestion-time decision), so this module
implements phase-05 §4 Step 2's algorithm now, under F6, matching its
published function signature and `EvaluationResult` shape exactly so that
whoever builds phase-05 next either reuses this module unmodified or moves
it verbatim -- no F6-specific narrowing was introduced. See
docs/decisions/0023-agents-phase-07-scp-engine-built-early.md.

Algorithm (phase-05 §4 Step 2, verbatim):
1. Start with effective_allowed = ALL.
2. For each level from root to target:
   - Union of Allow-Action sets across the level's policies (FullAWSAccess
     treated as `*`).
   - Union of Deny-Action sets.
   - effective_allowed ∩= allowed_at_level, effective_allowed -= denied_at_level.
3. NotAction inverts action matching.
4. NotResource inverts resource matching.
5. Conditions: conservative "may apply" -- a Deny with a condition is
   applied regardless of whether the condition would match, UNLESS it is
   aws:PrincipalIsAWSService=true and the caller is a service-linked role.
6. Wildcard actions matched via fnmatch.fnmatchcase on lowercased actions.

This module evaluates one concrete `action` per call rather than
materializing the full "ALL actions" set the algorithm's prose describes --
no AWS API enumerates "every IAM action that exists" as a finite set to
intersect against, so `effective_allowed` is tracked as a boolean per call
(allowed-so-far) rather than a real set, which is observationally identical
for a single-action query and is what every one of phase-05's own listed
consumers (BlockedInvocation, ShadowViolation) actually need.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from typing import Any, Literal, TypedDict

_READ_LIKE_PLACEHOLDER = "*"  # FullAWSAccess / any Allow-Action wildcard


class PolicyRef(TypedDict):
    arn: str
    name: str
    document: dict[str, Any]


class LevelPolicies(TypedDict):
    level: Literal["root", "ou", "account"]
    policies: list[PolicyRef]


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    allowed: bool
    denying_policy_arn: str | None = None
    denying_statement_id: str | None = None
    denying_level: str | None = None


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value]


def _statements(document: dict[str, Any]) -> list[dict[str, Any]]:
    statement = document.get("Statement", [])
    if isinstance(statement, dict):
        return [statement]
    return list(statement)


def _matches_action(statement: dict[str, Any], action: str) -> bool:
    lowered_action = action.lower()
    if "NotAction" in statement:
        patterns = _as_list(statement.get("NotAction"))
        matched = any(fnmatch.fnmatchcase(lowered_action, p.lower()) for p in patterns)
        return not matched
    patterns = _as_list(statement.get("Action"))
    return any(fnmatch.fnmatchcase(lowered_action, p.lower()) for p in patterns)


def _matches_resource(statement: dict[str, Any], resource: str) -> bool:
    lowered_resource = resource.lower()
    if "NotResource" in statement:
        patterns = _as_list(statement.get("NotResource"))
        matched = any(fnmatch.fnmatchcase(lowered_resource, p.lower()) for p in patterns)
        return not matched
    patterns = _as_list(statement.get("Resource")) or [_READ_LIKE_PLACEHOLDER]
    return any(fnmatch.fnmatchcase(lowered_resource, p.lower()) for p in patterns)


def _is_service_linked_role(principal_arn: str | None) -> bool:
    return principal_arn is not None and ":role/aws-service-role/" in principal_arn


def _deny_condition_applies(statement: dict[str, Any], *, principal_arn: str | None) -> bool:
    """Conservative "may apply" per phase-05 §4 Step 2 clause 5: a Deny with
    a Condition block is treated as applying regardless of whether AWS would
    actually evaluate the condition true at runtime, UNLESS the condition is
    `aws:PrincipalIsAWSService=true` and the caller is a service-linked role
    -- SLRs are the one case the spec calls out as a real, common false
    positive (every account's SLRs would otherwise show as "would be
    denied" by any Deny carrying that one guard condition).
    """
    condition = statement.get("Condition")
    if not condition:
        return True
    if not _is_service_linked_role(principal_arn):
        return True
    for operator_block in condition.values():
        if not isinstance(operator_block, dict):
            continue
        raw = operator_block.get("aws:PrincipalIsAWSService")
        values = _as_list(raw)
        if any(v.lower() == "true" for v in values):
            return False
    return True


@dataclass(frozen=True, slots=True)
class _DenyHit:
    policy_arn: str
    statement_id: str | None
    level: str


def _level_restricts_action(level_entry: LevelPolicies, action: str, resource: str) -> bool:
    """True if this level has at least one Allow statement AND none of them
    matches `action`/`resource` -- i.e. the level's own Allow set doesn't
    cover this call, so `effective_allowed` narrows to exclude it (phase-05
    §4 Step 2, clause 2's "effective_allowed ∩= allowed_at_level"). A level
    with zero Allow statements imposes no restriction (SCPs are opt-in
    restrictions, not opt-in grants).
    """
    has_allow_statement = False
    allow_matches = False
    for policy in level_entry["policies"]:
        for statement in _statements(policy["document"]):
            if statement.get("Effect") != "Allow":
                continue
            has_allow_statement = True
            if _matches_action(statement, action) and _matches_resource(statement, resource):
                allow_matches = True
    return has_allow_statement and not allow_matches


def _first_deny_hit(
    level_entry: LevelPolicies, action: str, resource: str, *, principal_arn: str | None
) -> _DenyHit | None:
    for policy in level_entry["policies"]:
        for statement in _statements(policy["document"]):
            if statement.get("Effect") != "Deny":
                continue
            if not (_matches_action(statement, action) and _matches_resource(statement, resource)):
                continue
            if not _deny_condition_applies(statement, principal_arn=principal_arn):
                continue
            return _DenyHit(
                policy_arn=policy["arn"],
                statement_id=statement.get("Sid"),
                level=level_entry["level"],
            )
    return None


def evaluate_action(
    chain: list[LevelPolicies],
    action: str,
    resource: str = "*",
    principal_tags: dict[str, str] | None = None,
    principal_arn: str | None = None,
) -> EvaluationResult:
    """Evaluate whether `action` on `resource` is allowed by the SCP chain.

    `chain` is ordered root -> ... -> target (whatever the caller's target
    is -- F6 passes root + every OU with no account level, per
    phase-07 §4 Step 2's "would-be-denied-in-a-member-account" framing;
    phase-05 passes root + OU + account for a real target).
    `principal_tags` is accepted for interface parity with phase-05's
    published signature; no statement-matching rule in this module keys off
    it yet (SCPs condition on `aws:PrincipalTag/*` far less often than on
    `aws:PrincipalIsAWSService`) -- unused, not dead: a future caller of
    this shared engine can start passing tag-keyed conditions without a
    signature change.
    """
    _ = principal_tags  # interface parity with phase-05 §4 Step 2; see docstring
    allowed = True
    denying_hit: _DenyHit | None = None
    restricting_level: str | None = None

    for level_entry in chain:
        if not level_entry["policies"]:
            continue

        if _level_restricts_action(level_entry, action, resource):
            allowed = False
            restricting_level = restricting_level or level_entry["level"]

        if denying_hit is None:
            denying_hit = _first_deny_hit(
                level_entry, action, resource, principal_arn=principal_arn
            )
            if denying_hit is not None:
                allowed = False

    if denying_hit is not None:
        return EvaluationResult(
            allowed=False,
            denying_policy_arn=denying_hit.policy_arn,
            denying_statement_id=denying_hit.statement_id,
            denying_level=denying_hit.level,
        )
    return EvaluationResult(
        allowed=allowed, denying_level=restricting_level if not allowed else None
    )
