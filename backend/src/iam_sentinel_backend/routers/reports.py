"""`GET /reports/weekly/{report_kind}`, `GET /reports/{key:path}` (backend
phase-04 §2/§3).
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from fastapi import APIRouter, Depends

from iam_sentinel_backend.deps import get_principal, get_reports_service
from iam_sentinel_backend.envelope import ok

if TYPE_CHECKING:
    from iam_sentinel_backend.auth.principal import Principal
    from iam_sentinel_backend.services.reports_service import ReportsService

router = APIRouter(tags=["reports"])


@router.get("/reports/weekly/{report_kind}")
def latest_weekly_report(
    report_kind: str,
    _principal: Principal = Depends(get_principal),
    reports_service: ReportsService = Depends(get_reports_service),
) -> dict[str, Any]:
    report = reports_service.latest_weekly_report(report_kind)
    return ok(report)


@router.get("/reports/{key:path}")
def get_report(
    key: str,
    _principal: Principal = Depends(get_principal),
    reports_service: ReportsService = Depends(get_reports_service),
) -> dict[str, Any]:
    report = reports_service.get_report_by_key(key)
    return ok(report)
