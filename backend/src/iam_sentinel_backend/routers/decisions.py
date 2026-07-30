"""`GET /decisions`, `GET /decisions/{id}` (backend phase-01 §3, §6)."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from fastapi import APIRouter, Depends, Query

from iam_sentinel_backend.deps import get_decisions_service, get_principal
from iam_sentinel_backend.envelope import ok

if TYPE_CHECKING:
    from iam_sentinel_backend.auth.principal import Principal
    from iam_sentinel_backend.services.decisions_service import DecisionsService

router = APIRouter(tags=["decisions"])


@router.get("/decisions")
def list_decisions(
    since: str | None = None,
    principal_filter: str | None = Query(default=None, alias="principal"),
    limit: int = Query(default=25, ge=1, le=100),
    next_token: str | None = None,
    principal: Principal = Depends(get_principal),
    decisions_service: DecisionsService = Depends(get_decisions_service),
) -> dict[str, Any]:
    page = decisions_service.list_decisions(
        principal=principal,
        since_iso=since,
        principal_filter=principal_filter,
        limit=limit,
        next_token=next_token,
    )
    return ok(page)


@router.get("/decisions/{decision_id}")
def get_decision(
    decision_id: str,
    principal: Principal = Depends(get_principal),
    decisions_service: DecisionsService = Depends(get_decisions_service),
) -> dict[str, Any]:
    decision = decisions_service.get_decision(principal=principal, decision_id=decision_id)
    return ok(decision)
