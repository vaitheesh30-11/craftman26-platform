"""IAM action pattern expansion for the SLR conflict scan (phase-09 §4
Step 3): "expand wildcards using the SLR DB action space (union of all
actions across all SLRs) via fnmatch.fnmatchcase on lowercased actions."
IAM action patterns use the same glob-like `*`/`?` grammar as ARN Resource
patterns (see tools/f1/wildcard.py) -- `fnmatchcase` on lowercased strings
matches that grammar case-insensitively, exactly as IAM itself treats
action names.
"""

from __future__ import annotations

from fnmatch import fnmatchcase
from typing import Any


def normalize_actions(raw: Any) -> list[str]:
    """IAM's `Action` field is `str | list[str]` in a Statement."""
    if isinstance(raw, str):
        return [raw]
    return [str(action) for action in raw]


def build_action_universe(slr_rows: list[dict[str, Any]]) -> dict[str, str]:
    """Union of every `required_actions` + `optional_actions` action across
    every SLR row, keyed by lowercased action with the original casing as
    the value -- callers expand Deny wildcards against this universe, then
    report `blocked_actions` back in the DB's own casing.
    """
    universe: dict[str, str] = {}
    for row in slr_rows:
        for action in [*row.get("required_actions", []), *row.get("optional_actions", [])]:
            universe.setdefault(str(action).lower(), str(action))
    return universe


def expand_action_patterns(patterns: list[str], universe: dict[str, str]) -> dict[str, str]:
    """Every universe action matched by any of `patterns`, keyed lowercased
    with original casing as the value. A pattern that is itself a concrete
    action (no wildcard) still matches via `fnmatchcase`'s exact-match case.
    """
    matched: dict[str, str] = {}
    for pattern in patterns:
        lowered_pattern = pattern.lower()
        for lowered_action, original in universe.items():
            if fnmatchcase(lowered_action, lowered_pattern):
                matched[lowered_action] = original
    return matched
