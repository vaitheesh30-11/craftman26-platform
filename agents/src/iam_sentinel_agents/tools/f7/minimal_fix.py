"""Minimal-fix synthesis for a collision's denying SCP (phase-08 §4 Step 4).

Two deterministic strategies, chosen by inspecting the denying statement's
own `Action` list -- never a third, LLM-authored option, since §9's
acceptance criterion ("every collision has a valid minimal_fix, SCP JSON
schema check") requires the patch to be independently re-derivable and
schema-valid without invoking a model:

- `remove_action_from_list`: the colliding action is one of several literal
  actions in the Deny statement's `Action` list -- the smallest patch is to
  drop just that action, per phase-08's "change Deny action-set to exclude
  the specific action" wording.
- `condition_exemption`: the Deny statement's `Action` is a wildcard (e.g.
  `s3:*`) or a single-item list equal to the collision action -- dropping
  the action from the list would leave an empty/meaningless statement, so
  the smallest patch instead adds a `Condition` exempting the statement via
  a dedicated tag key, per phase-08's "Add a Condition element that exempts
  the specific principal or resource" wording and §10's mute-record
  precedent (`aws:PrincipalTag/*` is the same condition family §10 already
  uses for operator-acknowledged collisions).
"""

from __future__ import annotations

from typing import Any, Literal

_EXEMPTION_CONDITION_KEY = "aws:PrincipalTag/SentinelCollisionExempt"

MinimalFixStrategy = Literal["remove_action_from_list", "condition_exemption"]


def build_minimal_fix(
    *,
    action: str,
    denying_statement_id: str | None,
    denying_action_patterns: list[str],
    denying_resource_patterns: list[str],
) -> dict[str, Any]:
    lowered_action = action.lower()
    literal_matches = [
        pattern for pattern in denying_action_patterns if pattern.lower() == lowered_action
    ]

    if literal_matches and len(denying_action_patterns) > 1:
        remaining = [
            pattern for pattern in denying_action_patterns if pattern.lower() != lowered_action
        ]
        strategy: MinimalFixStrategy = "remove_action_from_list"
        patched_statement: dict[str, Any] = {
            "Sid": denying_statement_id or "PatchedDeny",
            "Effect": "Deny",
            "Action": remaining,
            "Resource": denying_resource_patterns or ["*"],
        }
    else:
        strategy = "condition_exemption"
        patched_statement = {
            "Sid": denying_statement_id or "PatchedDeny",
            "Effect": "Deny",
            "Action": denying_action_patterns or [action],
            "Resource": denying_resource_patterns or ["*"],
            "Condition": {
                "StringNotEquals": {_EXEMPTION_CONDITION_KEY: "true"},
            },
        }

    return {
        "action": action,
        "denying_statement_id": denying_statement_id,
        "strategy": strategy,
        "patched_statement": patched_statement,
    }


def is_valid_scp_statement(statement: dict[str, Any]) -> bool:
    """Minimal structural check standing in for a full AWS SCP JSON-schema
    validator (phase-08 §9's acceptance criterion). Checks the shape every
    `minimal_fix.patched_statement` must have to be a syntactically legal
    SCP statement: `Effect` in {Allow, Deny}, exactly one of Action/NotAction
    present as a non-empty-typed list, and Resource present.
    """
    if statement.get("Effect") not in {"Allow", "Deny"}:
        return False
    has_action = isinstance(statement.get("Action"), list)
    has_not_action = isinstance(statement.get("NotAction"), list)
    if has_action == has_not_action:  # exactly one must be present
        return False
    if "Resource" not in statement:
        return False
    condition = statement.get("Condition")
    return condition is None or isinstance(condition, dict)
