"""`GET /evidence/{ref}` (backend phase-04 §2/§3/§5)."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from fastapi import APIRouter, Depends

from iam_sentinel_backend.deps import get_evidence_service, get_principal
from iam_sentinel_backend.envelope import ok

if TYPE_CHECKING:
    from iam_sentinel_backend.auth.principal import Principal
    from iam_sentinel_backend.services.evidence_service import EvidenceService

router = APIRouter(tags=["evidence"])


@router.get("/evidence/{ref:path}")
def get_evidence(
    ref: str,
    principal: Principal = Depends(get_principal),
    evidence_service: EvidenceService = Depends(get_evidence_service),
) -> dict[str, Any]:
    body = evidence_service.get_evidence(principal=principal, ref=ref)
    return ok(body)
