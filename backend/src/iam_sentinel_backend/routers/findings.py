"""`GET /findings`, `GET /findings/{id}` (backend phase-01 §3, §6)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, TYPE_CHECKING

from fastapi import APIRouter, Depends, Query

from iam_sentinel_backend.deps import get_findings_service, get_principal
from iam_sentinel_backend.envelope import ok

if TYPE_CHECKING:
    from iam_sentinel_backend.auth.principal import Principal
    from iam_sentinel_backend.services.findings_service import FindingsService

router = APIRouter(tags=["findings"])


@router.get("/findings")
def list_findings(
    severity: str | None = None,
    feature_id: str | None = None,
    account_id: str | None = None,
    principal_arn: str | None = None,
    since: datetime | None = None,
    limit: int = Query(default=25, ge=1, le=100),
    next_token: str | None = None,
    principal: Principal = Depends(get_principal),
    findings_service: FindingsService = Depends(get_findings_service),
) -> dict[str, Any]:
    page = findings_service.list_findings(
        principal=principal,
        severity=severity,
        feature_id=feature_id,
        account_id=account_id,
        principal_arn=principal_arn,
        since=since,
        limit=limit,
        next_token=next_token,
    )
    return ok(page)


@router.get("/findings/{finding_id}")
def get_finding(
    finding_id: str,
    account_id: str | None = None,
    feature_id: str | None = None,
    principal: Principal = Depends(get_principal),
    findings_service: FindingsService = Depends(get_findings_service),
) -> dict[str, Any]:
    finding = findings_service.get_finding(
        principal=principal, finding_id=finding_id, account_id=account_id, feature_id=feature_id
    )
    return ok(finding)
