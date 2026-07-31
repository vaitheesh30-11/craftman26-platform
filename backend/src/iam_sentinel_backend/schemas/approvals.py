"""`POST /decisions/{id}/approve|reject` (backend phase-03 §3 contract).

`ApprovalRequest.remediation_index` selects which entry of the decision's
`remediations_proposed` to act on -- a `DecisionRecord` may carry more than
one proposed remediation (`docs/DATA_CONTRACTS.md` §7). `dry_run` only
applies to approve; reject ignores it (there is nothing to apply either
way, see `services/approval_service.py`).
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from iam_sentinel_backend.schemas.common import RequestBase, ResponseBase

ApprovalOutcome = Literal["SUCCEEDED", "ROLLED_BACK", "REJECTED"]


class ApprovalRequest(RequestBase):
    remediation_index: int = Field(default=0, ge=0)
    reason: str = Field(default="", max_length=2048)
    dry_run: bool = False


class ApprovalResponse(ResponseBase):
    decision_id: str
    remediation_applied: dict[str, object] = Field(default_factory=dict)
    state_machine_execution_arn: str | None = None
    state: ApprovalOutcome
