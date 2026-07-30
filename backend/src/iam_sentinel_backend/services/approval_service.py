"""`POST /decisions/{id}/approve|reject` (backend phase-01 §3 -- "see
phase-03"). Scoped to the decision-record status transition only; the
Zelkova pre-check-gated remediation-apply workflow is `backend/docs/
phase-03-approval-workflow.txt`'s deliverable. See `schemas/approvals.py`
and ADR 0018.
"""

from __future__ import annotations

from datetime import datetime, UTC
from typing import Literal, TYPE_CHECKING

from fastapi import status

from iam_sentinel_backend.errors import SentinelHTTPException
from iam_sentinel_backend.schemas.approvals import ApprovalResponse

if TYPE_CHECKING:
    from iam_sentinel_adapters.ddb.decisions import DecisionsClient

    from iam_sentinel_backend.auth.principal import Principal

_TRANSITIONABLE_STATUSES = {"ANSWERED", "ESCALATED"}


class ApprovalService:
    def __init__(self, decisions_client: DecisionsClient) -> None:
        self._decisions = decisions_client

    def approve(self, *, principal: Principal, decision_id: str, reason: str) -> ApprovalResponse:
        return self._transition(
            principal=principal,
            decision_id=decision_id,
            reason=reason,
            new_status="AUTO_REMEDIATED",
        )

    def reject(self, *, principal: Principal, decision_id: str, reason: str) -> ApprovalResponse:
        return self._transition(
            principal=principal, decision_id=decision_id, reason=reason, new_status="REJECTED"
        )

    def _transition(
        self,
        *,
        principal: Principal,
        decision_id: str,
        reason: str,
        new_status: Literal["AUTO_REMEDIATED", "REJECTED"],
    ) -> ApprovalResponse:
        item = self._decisions.get_by_id(decision_id, principal=principal.arn)
        if item is None:
            raise SentinelHTTPException(
                code="DECISION_NOT_FOUND",
                message=f"no decision {decision_id!r} for this principal",
                http_status=status.HTTP_404_NOT_FOUND,
            )
        if item.get("status") not in _TRANSITIONABLE_STATUSES:
            raise SentinelHTTPException(
                code="DECISION_NOT_TRANSITIONABLE",
                message=f"decision {decision_id!r} is already {item.get('status')!r}",
                http_status=status.HTTP_409_CONFLICT,
            )

        updated = {
            **item,
            "status": new_status,
            "approval_reason": reason,
            "approval_actor": principal.arn,
            "approval_decided_at": datetime.now(UTC).isoformat(),
        }
        self._decisions.put(updated)
        return ApprovalResponse(decision_id=decision_id, status=new_status)
