"""Severity rubric for F4 Findings (phase-05 SS4 Step 6). Unlike F1's
`blast_score` (which feeds `PassRoleBlastPayload.blast_score` directly),
`BlockedInvocation` carries no severity field of its own (phase-05 SS3) --
Step 7 assigns severity per Finding, one per impacted role, so this rubric
is applied by the specialist prompt when it builds each Finding, not by
`scp_impact_simulate` itself.

`is_production_account` is always `None` in practice: `scp_impact_simulate`'s
own OpenAPI request body (`chain`, `proposed_scp`, `history`, `mode`) carries
no account id, so no tool in this phase can call
`organizations:ListTagsForResource` to learn it (see docs/decisions/0023).
The parameter is kept, not deleted, so a future phase that threads account
tags through some other path can raise CRITICAL without changing this
function's contract; today every call falls back to the call-count-only
rubric phase-05 SS10's own Risk section names as the documented fallback
for exactly this situation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from iam_sentinel_agents.contracts.common import Severity

_CRITICAL_CALL_THRESHOLD = 1000
_HIGH_CALL_THRESHOLD = 100


def assign_severity(call_count: int, *, is_production_account: bool | None = None) -> Severity:
    if call_count >= _CRITICAL_CALL_THRESHOLD and is_production_account:
        return "CRITICAL"
    if call_count >= _HIGH_CALL_THRESHOLD:
        return "HIGH"
    return "MEDIUM"
