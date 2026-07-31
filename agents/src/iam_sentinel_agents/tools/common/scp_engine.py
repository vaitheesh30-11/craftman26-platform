"""SCP evaluation engine -- computes the effective policy and collision
points across an ordered root-to-account SCP chain.

phase-08 §2 ("Reuses `common/scp_engine.py` from phase-05") assumes F4's SCP
Impact Analyst (agents/docs/phase-05-scp-impact-analyst.txt) already shipped
this module. It hasn't: only F1 (agents phase-02) exists on `main` so far.
This module is therefore built here, under `tools/common/` (not `tools/f7/`)
so F4 -- whenever its phase runs -- imports the same engine rather than
either duplicating it or F7 depending on a `tools/f7` import from `tools/f4`
(the wrong dependency direction for a "common" primitive). See
docs/decisions/0023.

Evaluation model
----------------
IAM's action namespace is unbounded, so this engine does not attempt to
enumerate "every action" -- it evaluates the bounded set of action patterns
actually mentioned by an Allow or Deny statement anywhere in the chain (the
"candidate actions"). This is exactly the set a collision-detection and
effective-policy report needs: an action nobody's SCP ever mentions is
trivially unaffected by the whole exercise.

For each candidate action `a` and level `L` (root -> ... -> account):
  local_allow(L, a)  = True if L has NO SCPs attached (no restriction), OR
                        any Allow statement at L (including the AWS-managed
                        `FullAWSAccess` default, whose Action is `"*"`)
                        matches `a`.
  local_deny(L, a)   = the first Deny statement at L matching `a`, if any.

Effective allow is the AND (intersection) of `local_allow` across every
level in the chain -- mirrors phase-08 §4 Step 2's "intersection with
parent's effective_allowed", applied root-down. Effective deny is the OR
(union) of `local_deny` across every level -- an explicit Deny at ANY level
removes the action everywhere, per AWS's documented SCP evaluation rule
(the same rule phase-08's own plain-English template cites). The final
effective policy is `AND(local_allow) AND NOT OR(local_deny)`.

A *collision* (phase-08 §4 Step 3) requires:
  - an EXPLICIT allow for `a` at some level L1 (a real Allow statement,
    excluding the `FullAWSAccess` default -- otherwise virtually every
    denied action would "collide", since `FullAWSAccess` allows everything
    by default and is attached almost everywhere), AND
  - a Deny for `a` at some level L2, AND
  - L1 != L2 ("at another level", phase-08 §4 Step 3's own wording).
"""

from __future__ import annotations

import json
from fnmatch import fnmatchcase
from typing import Any, Literal

ENGINE_VERSION = "1.0.0"

ScpLevel = Literal["root", "ou", "account"]
_FULL_AWS_ACCESS_NAME = "FullAWSAccess"
_FULL_AWS_ACCESS_ID = "p-FullAWSAccess"


class ScpPolicy:
    """One attached SCP's identity + document, normalized for the engine."""

    __slots__ = ("arn", "document", "name", "policy_id")

    def __init__(self, *, policy_id: str, name: str, arn: str, document: dict[str, Any]) -> None:
        self.policy_id = policy_id
        self.name = name
        self.arn = arn
        self.document = document

    @property
    def is_full_aws_access(self) -> bool:
        return self.policy_id == _FULL_AWS_ACCESS_ID or self.name == _FULL_AWS_ACCESS_NAME


class ScpLevelChain:
    """One level of the walked chain: its identity + attached policies."""

    __slots__ = ("level", "policies", "target_id")

    def __init__(self, *, level: ScpLevel, target_id: str, policies: list[ScpPolicy]) -> None:
        self.level = level
        self.target_id = target_id
        self.policies = policies


class _Statement:
    __slots__ = ("actions", "effect", "policy", "resources", "sid")

    def __init__(
        self,
        *,
        policy: ScpPolicy,
        effect: str,
        actions: list[str],
        resources: list[str],
        sid: str | None,
    ) -> None:
        self.policy = policy
        self.effect = effect
        self.actions = actions
        self.resources = resources
        self.sid = sid


def normalize_policy_document(raw: Any) -> dict[str, Any]:
    """Same shape of defensiveness as `tools/f1/scan.normalize_policy_document`
    -- boto3's Organizations `DescribePolicy` returns `Content` as a JSON
    string, never a pre-parsed dict.
    """
    if isinstance(raw, str):
        return dict(json.loads(raw))
    return dict(raw)


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value]


def _statements_for_policy(policy: ScpPolicy) -> list[_Statement]:
    raw_statements = policy.document.get("Statement", [])
    statements = [raw_statements] if isinstance(raw_statements, dict) else list(raw_statements)
    return [
        _Statement(
            policy=policy,
            effect=str(statement.get("Effect", "")),
            actions=_as_list(statement.get("Action")),
            resources=_as_list(statement.get("Resource")) or ["*"],
            sid=statement.get("Sid"),
        )
        for statement in statements
    ]


def _action_matches(patterns: list[str], action: str) -> bool:
    lowered = action.lower()
    return any(fnmatchcase(lowered, pattern.lower()) for pattern in patterns)


def _candidate_actions(levels: list[ScpLevelChain]) -> list[str]:
    seen: dict[str, None] = {}
    for level in levels:
        for policy in level.policies:
            for statement in _statements_for_policy(policy):
                for action in statement.actions:
                    if action != "*":
                        seen.setdefault(action, None)
    return list(seen)


def _level_statements(level: ScpLevelChain) -> list[_Statement]:
    return [statement for policy in level.policies for statement in _statements_for_policy(policy)]


def _first_explicit_allow(statements: list[_Statement], action: str) -> _Statement | None:
    for statement in statements:
        if statement.effect != "Allow" or statement.policy.is_full_aws_access:
            continue
        if _action_matches(statement.actions, action):
            return statement
    return None


def _first_deny(statements: list[_Statement], action: str) -> _Statement | None:
    for statement in statements:
        if statement.effect == "Deny" and _action_matches(statement.actions, action):
            return statement
    return None


def _local_allow(statements: list[_Statement], action: str) -> bool:
    if not statements:
        # No SCPs attached at this level at all -- no restriction imposed.
        return True
    return any(
        statement.effect == "Allow" and _action_matches(statement.actions, action)
        for statement in statements
    )


class _ActionProvenance:
    __slots__ = ("allow_level", "allow_statement", "deny_level", "deny_statement", "effective")

    def __init__(self) -> None:
        self.effective: bool = True
        self.allow_level: ScpLevelChain | None = None
        self.allow_statement: _Statement | None = None
        self.deny_level: ScpLevelChain | None = None
        self.deny_statement: _Statement | None = None


def _evaluate_action(levels: list[ScpLevelChain], action: str) -> _ActionProvenance:
    provenance = _ActionProvenance()
    for level in levels:
        statements = _level_statements(level)

        if not _local_allow(statements, action):
            provenance.effective = False

        if provenance.allow_statement is None:
            explicit_allow = _first_explicit_allow(statements, action)
            if explicit_allow is not None:
                provenance.allow_level = level
                provenance.allow_statement = explicit_allow

        if provenance.deny_statement is None:
            deny = _first_deny(statements, action)
            if deny is not None:
                provenance.deny_level = level
                provenance.deny_statement = deny
                provenance.effective = False

    return provenance


def compute_effective_policy(levels: list[ScpLevelChain]) -> dict[str, Any]:
    """Compute the merged effective policy + provenance across `levels`.

    Returns a dict with:
      - `effective_policy`: single-statement SCP-shaped JSON document
        (phase-08 §4 Step 2: "single Statement with Action as list").
      - `provenance`: {action: _ActionProvenance} for collision detection.
      - `candidate_actions`: the bounded action universe evaluated.
    """
    candidates = _candidate_actions(levels)
    provenance = {action: _evaluate_action(levels, action) for action in candidates}
    effective_actions = sorted(action for action, prov in provenance.items() if prov.effective)

    effective_policy: dict[str, Any] = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "EffectivePolicy",
                "Effect": "Allow",
                "Action": effective_actions,
                "Resource": "*",
            }
        ],
    }
    return {
        "effective_policy": effective_policy,
        "provenance": provenance,
        "candidate_actions": candidates,
    }


def find_collisions(provenance: dict[str, _ActionProvenance]) -> list[dict[str, Any]]:
    """Collision = explicit Allow at L1 AND Deny at L2, L1 != L2 (§4 Step 3).

    Deny always wins in this engine's subtractive model (see module
    docstring), so every qualifying pair is, definitionally, a case where
    "the Deny wins" -- there is no separate winner check to perform.

    Returns plain, JSON-serializable dicts (not the engine's internal
    `_Statement`/`ScpLevelChain` objects) -- `tools/f7/collision.py` builds
    `ScpCollision` contracts straight from this shape without reaching into
    engine-private classes.
    """
    collisions: list[dict[str, Any]] = []
    for action, prov in provenance.items():
        if prov.allow_statement is None or prov.deny_statement is None:
            continue
        if prov.allow_level is prov.deny_level:
            continue
        assert prov.allow_level is not None  # narrows for mypy; set alongside allow_statement
        assert prov.deny_level is not None  # narrows for mypy; set alongside deny_statement
        collisions.append(
            {
                "action": action,
                "resource_pattern": prov.deny_statement.resources[0]
                if prov.deny_statement.resources
                else "*",
                "allowed_by_scp_arn": prov.allow_statement.policy.arn,
                "allowed_by_scp_name": prov.allow_statement.policy.name,
                "allowed_at_level": prov.allow_level.level,
                "denied_by_scp_arn": prov.deny_statement.policy.arn,
                "denied_by_scp_name": prov.deny_statement.policy.name,
                "denied_at_level": prov.deny_level.level,
                "denying_statement_id": prov.deny_statement.sid,
                "denying_action_patterns": list(prov.deny_statement.actions),
                "denying_resource_patterns": list(prov.deny_statement.resources),
            }
        )
    return collisions


def local_allow_set(level: ScpLevelChain) -> set[str] | None:
    """Every action explicitly Allow-matched at `level`'s own statements, or
    `None` if the level imposes no restriction (no SCPs, or only
    `FullAWSAccess`) -- used by the "effective policy is a subset of every
    level's individual Allow set" property test (phase-08 §8).
    """
    statements = _level_statements(level)
    if not statements or all(statement.policy.is_full_aws_access for statement in statements):
        return None
    allowed = {
        action
        for statement in statements
        if statement.effect == "Allow"
        for action in statement.actions
        if action != "*"
    }
    return allowed
