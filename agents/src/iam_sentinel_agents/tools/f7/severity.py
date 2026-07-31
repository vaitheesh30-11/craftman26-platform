"""Collision severity rubric (phase-08 §4 Step 5).

`ScpCollision` (contracts/scp_collision.py) carries no severity field --
per phase-08 §3's own contract, severity is a `Finding`-level attribute, not
part of the tool's payload. This module is the deterministic function the
specialist's Finding-emission step calls once per collision.

Two of the three escalation inputs the spec names don't exist yet on
`main`:
  - "HIGH if the collision touches an action with >= 100 historical calls
    per F4's Athena reuse" -- F4 (phase-05) hasn't shipped.
  - "CRITICAL if ... an SLR-required action, cross-check with F8's DB" --
    F8 (phase-09) hasn't shipped.
Both are wired as optional, injectable inputs that default to "no data
available" rather than hard-coded to a specific data source, so F4/F8 can
supply real values later without changing this function's signature. Absent
real data, every collision resolves to the spec's own stated default
(MEDIUM) -- this is not a guess, it is phase-08 §10's own mitigation for the
SLR case ("if F8's DB is empty ... degrade CRITICAL to HIGH and note 'SLR DB
not yet initialized'"), applied one step further back since neither data
source is wired at all yet.
"""

from __future__ import annotations

from fnmatch import fnmatchcase
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Collection

    from iam_sentinel_agents.contracts.common import Severity

_HIGH_VOLUME_CALL_THRESHOLD = 100


def _action_in_slr_set(action: str, slr_required_actions: Collection[str]) -> bool:
    lowered = action.lower()
    return any(fnmatchcase(lowered, pattern.lower()) for pattern in slr_required_actions)


def compute_collision_severity(
    action: str,
    *,
    historical_call_count: int | None = None,
    slr_db_initialized: bool = False,
    slr_required_actions: Collection[str] = (),
) -> tuple[Severity, str | None]:
    """Returns (severity, degrade_reason). `degrade_reason` is non-None only
    when a higher severity was warranted but the supporting data source
    isn't wired yet (phase-08 §10's SLR mitigation, applied uniformly).
    """
    if slr_required_actions and _action_in_slr_set(action, slr_required_actions):
        if slr_db_initialized:
            return "CRITICAL", None
        return "HIGH", "SLR DB not yet initialized"

    if historical_call_count is not None and historical_call_count >= _HIGH_VOLUME_CALL_THRESHOLD:
        return "HIGH", None

    return "MEDIUM", None
