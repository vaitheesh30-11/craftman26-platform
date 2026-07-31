"""Impact classification rubric for an SLR conflict (phase-09 §4 Step 3):

- CRITICAL: intersection includes >= 30% of required_actions OR any of the
  core actions marked in `slr_seed.json` as "core:true".
- HIGH: 10-30%.
- MEDIUM: < 10%.

Only reachable with a non-empty intersection -- `evaluate_scp` never calls
this for an SLR row with zero blocked actions (that isn't a conflict).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from iam_sentinel_agents.contracts.slr import Impact

_CRITICAL_THRESHOLD = 0.30
_HIGH_THRESHOLD = 0.10


def classify_impact(*, intersection_count: int, required_count: int, core_hit: bool) -> Impact:
    ratio = intersection_count / required_count if required_count else 1.0
    if core_hit or ratio >= _CRITICAL_THRESHOLD:
        return "CRITICAL"
    if ratio >= _HIGH_THRESHOLD:
        return "HIGH"
    return "MEDIUM"
