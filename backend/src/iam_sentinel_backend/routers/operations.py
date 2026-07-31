"""`GET /operations/faults`, `GET /operations/cost/weekly` (backend
phase-01 §3, §7); `GET /operations/divergence`, `GET /operations/health`
(backend phase-04 §2/§3).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, TYPE_CHECKING

from fastapi import APIRouter, Depends, Query

from iam_sentinel_backend.deps import get_operations_service, get_principal
from iam_sentinel_backend.envelope import ok

if TYPE_CHECKING:
    from iam_sentinel_backend.auth.principal import Principal
    from iam_sentinel_backend.services.operations_service import OperationsService

router = APIRouter(tags=["operations"])


@router.get("/operations/faults")
def list_faults(
    fault_class: str | None = None,
    since: datetime | None = None,
    limit: int = Query(default=25, ge=1, le=100),
    next_token: str | None = None,
    _principal: Principal = Depends(get_principal),
    operations_service: OperationsService = Depends(get_operations_service),
) -> dict[str, Any]:
    page = operations_service.list_faults(
        fault_class=fault_class, since=since, limit=limit, next_token=next_token
    )
    return ok(page)


@router.get("/operations/cost/weekly")
def latest_cost_report(
    _principal: Principal = Depends(get_principal),
    operations_service: OperationsService = Depends(get_operations_service),
) -> dict[str, Any]:
    return ok(operations_service.latest_cost_report())


@router.get("/operations/divergence")
def list_divergence(
    feature_id: str | None = None,
    divergence_kind: str | None = None,
    since: datetime | None = None,
    limit: int = Query(default=25, ge=1, le=100),
    next_token: str | None = None,
    _principal: Principal = Depends(get_principal),
    operations_service: OperationsService = Depends(get_operations_service),
) -> dict[str, Any]:
    page = operations_service.list_divergence(
        feature_id=feature_id,
        divergence_kind=divergence_kind,
        since=since,
        limit=limit,
        next_token=next_token,
    )
    return ok(page)


@router.get("/operations/health")
def get_health(
    _principal: Principal = Depends(get_principal),
    operations_service: OperationsService = Depends(get_operations_service),
) -> dict[str, Any]:
    return ok(operations_service.get_health())
