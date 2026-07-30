"""`POST /decisions/{id}/approve|reject` (backend phase-01 §3 route table
says "see phase-03" -- the Zelkova pre-check-gated apply workflow is
`backend/docs/phase-03-approval-workflow.txt`'s deliverable, not built yet).
This phase implements the *decision-record status transition* half only
(ANSWERED/ESCALATED -> AUTO_REMEDIATED/REJECTED is out of scope until then);
attempting to actually apply a `RemediationPlan` here would duplicate
phase-03's Zelkova pre/post-check contract ahead of time with no adapter
support for `dry_run=False` application. See ADR 0018.
"""

from __future__ import annotations

from pydantic import Field

from iam_sentinel_backend.schemas.common import RequestBase, ResponseBase


class ApprovalRequest(RequestBase):
    reason: str = Field(default="", max_length=2048)


class ApprovalResponse(ResponseBase):
    decision_id: str
    status: str
