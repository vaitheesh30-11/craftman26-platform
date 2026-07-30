"""`POST /decisions/{id}/approve|reject` (backend phase-01 §3; full apply
workflow deferred to phase-03, see `services/approval_service.py`).
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from fastapi import APIRouter, Depends

from iam_sentinel_backend.deps import get_approval_service, get_principal
from iam_sentinel_backend.envelope import ok
from iam_sentinel_backend.schemas.approvals import ApprovalRequest

if TYPE_CHECKING:
    from iam_sentinel_backend.auth.principal import Principal
    from iam_sentinel_backend.services.approval_service import ApprovalService

router = APIRouter(tags=["approvals"])


@router.post("/decisions/{decision_id}/approve")
def approve_decision(
    decision_id: str,
    request: ApprovalRequest,
    principal: Principal = Depends(get_principal),
    approval_service: ApprovalService = Depends(get_approval_service),
) -> dict[str, Any]:
    result = approval_service.approve(
        principal=principal, decision_id=decision_id, reason=request.reason
    )
    return ok(result)


@router.post("/decisions/{decision_id}/reject")
def reject_decision(
    decision_id: str,
    request: ApprovalRequest,
    principal: Principal = Depends(get_principal),
    approval_service: ApprovalService = Depends(get_approval_service),
) -> dict[str, Any]:
    result = approval_service.reject(
        principal=principal, decision_id=decision_id, reason=request.reason
    )
    return ok(result)
