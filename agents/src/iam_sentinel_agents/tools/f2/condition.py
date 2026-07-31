"""Matches an Access Analyzer finding's `condition` map against real AWS
Organizations data (phase-03 §4 Step 3).

`GetFinding`'s `condition` field is already a flattened `dict[str, str]` --
the operator (`StringEquals`, `ForAnyValue:StringEquals`, `StringLike`,
`ArnEquals`, `ArnLike`, ...) that produced it in the original resource
policy does not survive as a separate field. Two things fall out of that:

- `ForAnyValue:*` operators become a comma-joined multi-value string in
  practice (Access Analyzer's own documented condition-value flattening) --
  `_split_values` treats every value as potentially multi-valued rather than
  branching on operator name, which we don't have.
- `StringEquals`/`ArnEquals` (exact) and `StringLike`/`ArnLike` (glob) are
  indistinguishable from the flattened map alone. Matching via
  `fnmatch.fnmatchcase` subsumes both correctly: a pattern with no `*`/`?`
  degenerates to an exact match, and IAM's own Resource/Condition wildcard
  grammar is exactly `fnmatchcase`'s grammar (see `tools/f1/wildcard.py`,
  the established precedent for this exact call).
"""

from __future__ import annotations

from fnmatch import fnmatchcase
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

ORG_ID_CONDITION_KEY = "aws:PrincipalOrgId"
ACCOUNT_CONDITION_KEY = "aws:PrincipalAccount"
ORG_PATHS_CONDITION_KEY = "aws:PrincipalOrgPaths"


def _split_values(raw: str) -> list[str]:
    return [value.strip() for value in raw.split(",") if value.strip()]


def _normalize(value: str) -> str:
    return value.strip().lower()


def condition_values(condition: dict[str, str], key: str) -> list[str]:
    raw = condition.get(key)
    if raw is None:
        return []
    return _split_values(raw)


def org_id_matches(condition: dict[str, str], org_id: str) -> str | None:
    """Returns the matched condition value, or None if no value matches."""
    normalized_org_id = _normalize(org_id)
    for value in condition_values(condition, ORG_ID_CONDITION_KEY):
        if fnmatchcase(normalized_org_id, _normalize(value)):
            return value
    return None


def account_matches(condition: dict[str, str], real_account_ids: Iterable[str]) -> str | None:
    """Returns the matched condition value, or None if no value matches."""
    accounts = list(real_account_ids)
    for value in condition_values(condition, ACCOUNT_CONDITION_KEY):
        if any(fnmatchcase(account_id, value) for account_id in accounts):
            return value
    return None


def org_paths_match(condition: dict[str, str], real_ou_paths: Iterable[str]) -> str | None:
    """Returns the matched condition value (the pattern), or None if no
    real OU path matches it.
    """
    paths = [_normalize(path) for path in real_ou_paths]
    for value in condition_values(condition, ORG_PATHS_CONDITION_KEY):
        normalized_pattern = _normalize(value)
        if any(fnmatchcase(path, normalized_pattern) for path in paths):
            return value
    return None
