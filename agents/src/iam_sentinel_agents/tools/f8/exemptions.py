"""Exemption-statement generation and merge (phase-09 §4 Step 4).

Two strategies, Strategy A preferred:
- Strategy A (specific): `ArnNotLike` on `aws:PrincipalArn` scoped to the
  conflicting service's own `aws-service-role/<service_principal>/*` path.
- Strategy B (broad): `Bool` on `aws:PrincipalIsAWSService` -- used once a
  single Deny statement's conflict count exceeds the threshold, per §4's
  own risk trade-off (§10: "default to Strategy B once conflict count > 3").

`apply_exemptions` mutates a Deny statement's `Condition` block in place.
Only `Condition` is ever added or extended here -- never a new Allow
statement and never a change to `Effect`/`Action`/`Resource`, per the
specialist prompt's SAFETY clause and phase-09 §4 Step 4's own "safe_scp
still enforces the original intent" requirement.
"""

from __future__ import annotations

from typing import Any

_STRATEGY_A_MAX_CONFLICTS = 3  # spec §4 Step 4: "> 3" switches to Strategy B


def strategy_a_condition(service_principal: str) -> dict[str, dict[str, object]]:
    return {
        "ArnNotLike": {
            "aws:PrincipalArn": f"arn:aws:iam::*:role/aws-service-role/{service_principal}/*"
        }
    }


def strategy_b_condition() -> dict[str, dict[str, object]]:
    return {"Bool": {"aws:PrincipalIsAWSService": "false"}}


def merge_condition(statement: dict[str, Any], addition: dict[str, dict[str, object]]) -> None:
    """Deep-merge one `{operator: {key: value}}` condition block into a
    statement's existing `Condition`, deduplicating list values rather than
    overwriting a key another SLR's exemption already populated.
    """
    condition = statement.setdefault("Condition", {})
    for operator, keys in addition.items():
        operator_block = condition.setdefault(operator, {})
        for key, value in keys.items():
            existing = operator_block.get(key)
            if existing is None:
                operator_block[key] = value
                continue
            existing_list = existing if isinstance(existing, list) else [existing]
            new_list = value if isinstance(value, list) else [value]
            merged = existing_list + [item for item in new_list if item not in existing_list]
            operator_block[key] = merged


def apply_exemptions(statement: dict[str, Any], conflicting_service_principals: list[str]) -> None:
    """Choose Strategy A (per-service) or Strategy B (broad) for one Deny
    statement based on how many distinct SLRs it conflicts with, then merge
    the chosen condition(s) into the statement.
    """
    if len(conflicting_service_principals) > _STRATEGY_A_MAX_CONFLICTS:
        merge_condition(statement, strategy_b_condition())
        return
    for service_principal in conflicting_service_principals:
        merge_condition(statement, strategy_a_condition(service_principal))
