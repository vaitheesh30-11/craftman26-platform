"""scp_policy_evaluator -- SCP evaluation engine for F4 (phase-05 SS4 Step 2).

Named `scp_engine` in the phase-05 spec, which also names F7 (Collision
Resolver, phase-08) as a second consumer -- but F7 merged to main first
(this phase hadn't landed yet) and built its own
`tools/common/scp_engine.py` with a different data model
(ScpPolicy/ScpLevelChain, root-to-account intersection/union across
multiple OU branches for collision detection) to match its own needs.
This module is renamed to avoid clobbering that file: the two are NOT
interchangeable (different function names, different levels-of-analysis --
this one evaluates a single action against one walked chain with
condition-key suppression; F7's compares provenance across chains) and
reconciling them into one shared engine is real, deferred work -- tracked
in this phase's ADR, not attempted here to avoid destabilizing F7's
already-merged, already-tested collision-detection logic.

Implements AWS's documented root-to-target SCP evaluation semantics for a
single (action, resource) pair against a walked policy chain: intersect
every level's Allow-action ceiling, subtract every level's explicit Deny,
and report which policy/statement/level is responsible the moment the
action becomes disallowed.

`iam:SimulatePrincipalPolicy` does not model this (phase-05 SS1) -- this
module is IAM Sentinel's replacement for it at the OU-inheritance layer.
"""

from __future__ import annotations

from fnmatch import fnmatchcase
from typing import Literal

from pydantic import Field

from iam_sentinel_agents.contracts.common import Base

Level = Literal["root", "ou", "account"]

# Bumped whenever the algorithm in this module changes in a way that could
# change a past evaluation's outcome -- `ScpImpactPayload.engine_version`
# lets a stored Finding be re-checked against the engine that produced it.
ENGINE_VERSION = "1.0.0"

_SLR_ARN_MARKER = "/aws-service-role/"
_PRINCIPAL_IS_AWS_SERVICE_KEY = "aws:principalisawsservice"


class PolicyRef(Base):
    arn: str = Field(min_length=1, max_length=2048)
    name: str = Field(min_length=1, max_length=256)
    document: dict[str, object]


class LevelPolicies(Base):
    level: Level
    target: str = Field(min_length=1, max_length=128)
    policies: list[PolicyRef] = Field(default_factory=list, max_length=64)


class EvaluationResult(Base):
    allowed: bool
    denying_policy_arn: str | None = None
    denying_statement_id: str | None = None
    denying_level: Level | None = None


def _as_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def iter_statements(document: dict[str, object]) -> list[dict[str, object]]:
    statement = document.get("Statement", [])
    if isinstance(statement, dict):
        return [statement]
    return [s for s in statement if isinstance(s, dict)] if isinstance(statement, list) else []


def _action_matches(statement: dict[str, object], action: str) -> bool:
    lowered_action = action.lower()
    if "NotAction" in statement:
        patterns = _as_list(statement.get("NotAction"))
        matched = any(fnmatchcase(lowered_action, pattern.lower()) for pattern in patterns)
        return not matched
    patterns = _as_list(statement.get("Action"))
    return any(fnmatchcase(lowered_action, pattern.lower()) for pattern in patterns)


def _resource_matches(statement: dict[str, object], resource: str) -> bool:
    lowered_resource = resource.lower()
    if "NotResource" in statement:
        patterns = _as_list(statement.get("NotResource"))
        matched = any(fnmatchcase(lowered_resource, pattern.lower()) for pattern in patterns)
        return not matched
    # SCP statements conventionally omit `Resource` entirely (it defaults to
    # "*"); an absent key must match everything, same as an explicit "*".
    patterns = _as_list(statement.get("Resource")) or ["*"]
    return any(fnmatchcase(lowered_resource, pattern.lower()) for pattern in patterns)


def _condition_suppresses_deny(statement: dict[str, object], *, principal_arn: str | None) -> bool:
    """phase-05 SS4 Step 2.5: a Deny carrying ANY condition is conservatively
    treated as "may apply" -- i.e. it still blocks -- with exactly one
    documented exception: `aws:PrincipalIsAWSService=true`. That condition
    key is knowably False for a service-*linked role* (an IAM role, not an
    AWS service principal itself), even though the SCP author likely
    intended it to exempt exactly this caller -- the real-world
    misconfiguration F8 (SLR Guardian) targets. Because the condition is
    knowably false for that caller, the Deny provably does not fire, so this
    is the one case the engine can resolve exactly rather than
    conservatively; every other condition is assumed to match.
    """
    condition = statement.get("Condition")
    if not isinstance(condition, dict) or not condition:
        return False
    is_slr = bool(principal_arn) and _SLR_ARN_MARKER in (principal_arn or "")
    if not is_slr:
        return False
    for operator_block in condition.values():
        if not isinstance(operator_block, dict):
            continue
        for key, value in operator_block.items():
            if key.lower() != _PRINCIPAL_IS_AWS_SERVICE_KEY:
                continue
            if any(v.lower() == "true" for v in _as_list(value)):
                return True
    return False


def _level_allow_and_deny(
    level_policies: LevelPolicies, action: str, resource: str, *, principal_arn: str | None
) -> tuple[bool, bool, tuple[str, str | None] | None]:
    """Returns `(has_allow_statement, is_allowed_by_level, deny_hit)`.

    `has_allow_statement` is True only if at least one policy at this level
    carries an `Effect: Allow` statement -- most real SCPs are Deny-only
    (they add restrictions without ever replacing the account's default
    FullAWSAccess ceiling), so a Deny-only level must never be treated as
    "this level's allow-list doesn't cover the action" -- only a level that
    actually defines an allow-list can narrow the ceiling that way.
    `deny_hit`, when not `None`, is `(policy_arn, statement_id)` for the
    first matching, non-suppressed Deny statement at this level.
    """
    has_allow_statement = False
    allowed = False
    deny_hit: tuple[str, str | None] | None = None
    for policy in level_policies.policies:
        for statement in iter_statements(policy.document):
            effect = statement.get("Effect")
            if effect == "Allow":
                has_allow_statement = True
                if _action_matches(statement, action) and _resource_matches(statement, resource):
                    allowed = True
            elif effect == "Deny" and deny_hit is None:
                if not (
                    _action_matches(statement, action) and _resource_matches(statement, resource)
                ):
                    continue
                if _condition_suppresses_deny(statement, principal_arn=principal_arn):
                    continue
                sid = statement.get("Sid")
                deny_hit = (policy.arn, sid if isinstance(sid, str) else None)
    return has_allow_statement, allowed, deny_hit


def evaluate_action(
    chain: list[LevelPolicies],
    action: str,
    resource: str = "*",
    principal_tags: dict[str, str] | None = None,  # noqa: ARG001 -- reserved for a future condition-aware caller (see module docstring); accepted now so F7 shares one signature
    principal_arn: str | None = None,
) -> EvaluationResult:
    """Evaluate whether `action` on `resource` survives the full
    root -> ... -> target SCP chain (phase-05 SS4 Step 2's algorithm).

    A Deny always wins outright. An action also becomes disallowed the
    moment any level's union of Allow statements stops covering it -- SCPs
    are a permissions *ceiling*, never a grant, so replacing a level's
    FullAWSAccess with a narrower allow-list excludes everything outside
    it even with no explicit Deny anywhere. `effective_allowed` only ever
    narrows while walking the chain, never widens (property tested).
    """
    effective_allowed = True
    denying_policy_arn: str | None = None
    denying_statement_id: str | None = None
    denying_level: Level | None = None

    for level_policies in chain:
        has_allow_statement, allowed_at_level, deny_hit = _level_allow_and_deny(
            level_policies, action, resource, principal_arn=principal_arn
        )
        if deny_hit is not None:
            effective_allowed = False
            denying_policy_arn, denying_statement_id = deny_hit
            denying_level = level_policies.level
            break
        if has_allow_statement and not allowed_at_level:
            effective_allowed = False
            denying_policy_arn = level_policies.policies[0].arn
            denying_statement_id = None
            denying_level = level_policies.level
            break

    return EvaluationResult(
        allowed=effective_allowed,
        denying_policy_arn=denying_policy_arn,
        denying_statement_id=denying_statement_id,
        denying_level=denying_level,
    )
