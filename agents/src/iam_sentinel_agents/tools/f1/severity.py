"""Blast-score rollup — phase-02 §3.3 rubric applied to a principal's full
set of `BlastPath`s. INFO is never returned: an empty path list means "no
reachable elevated privilege found in ≤2 hops", i.e. `LOW` (contained),
per §3.3's own wording, not "no data".
"""

from __future__ import annotations

from functools import reduce
from typing import TYPE_CHECKING

from iam_sentinel_agents.contracts.common import Severity, severity_max

if TYPE_CHECKING:
    from iam_sentinel_agents.contracts.passrole import BlastPath, ReachedPrivilege

_PRIVILEGE_TO_SEVERITY: dict[ReachedPrivilege, Severity] = {
    "AdministratorAccess": "CRITICAL",
    "PowerUserAccess": "HIGH",
    "IAMWrite": "HIGH",
    "SensitiveService": "MEDIUM",
    "Other": "LOW",
}


def blast_score(paths: list[BlastPath]) -> Severity:
    if not paths:
        return "LOW"
    scores = (_PRIVILEGE_TO_SEVERITY[path.reached_privilege] for path in paths)
    return reduce(severity_max, scores)
