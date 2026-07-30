"""`DecisionRecord` read model (mirrors `docs/DATA_CONTRACTS.md §7`).

`specialist_verdicts`/`remediations_*` are kept as loosely-typed dicts
rather than full `SpecialistVerdict`/`RemediationPlan` mirrors: those two
contracts are deep (nested `ToolInvocation`/`ZelkovaCheck`) and backend
phase-01 only *reads* already-validated `DecisionRecord`s that Prime's
post-turn Lambda wrote (that Lambda -- `agents/src/iam_sentinel_agents/
prime/post_turn.py` -- is the actual producer-side validator per the
contract's own rule "every producer validates before send"). Re-typing the
full nested shape here buys no additional safety and doubles the
maintenance surface for models this phase never constructs, only displays.
"""

from __future__ import annotations

from pydantic import Field

from iam_sentinel_backend.schemas.common import DecisionStatus, ResponseBase
from iam_sentinel_backend.schemas.finding import FindingOut


class DecisionOut(ResponseBase):
    decision_id: str
    correlation_id: str
    principal: str
    query: dict[str, object] = Field(default_factory=dict)
    specialist_verdicts: list[dict[str, object]] = Field(default_factory=list)
    findings: list[FindingOut] = Field(default_factory=list)
    remediations_proposed: list[dict[str, object]] = Field(default_factory=list)
    remediations_applied: list[dict[str, object]] = Field(default_factory=list)
    status: DecisionStatus
    narrative: str
    evidence_ref: dict[str, object] = Field(default_factory=dict)
    decided_at: str


class DecisionsPage(ResponseBase):
    items: list[DecisionOut]
    next_token: str | None = None
