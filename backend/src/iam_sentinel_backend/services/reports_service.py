"""`GET /reports/weekly/{report_kind}`, `GET /reports/{key:path}` (backend
phase-04 §2/§4 step 1). No access-control scoping per the spec §5 -- reports
are operator-facing observability views, same precedent as
`OperationsService`, not principal-scoped data.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import status

from iam_sentinel_backend.errors import SentinelHTTPException
from iam_sentinel_backend.schemas.reports import ReportOut

if TYPE_CHECKING:
    from iam_sentinel_adapters.s3.reports import ReportsClient


class ReportsService:
    def __init__(self, reports_client: ReportsClient) -> None:
        self._reports = reports_client

    def latest_weekly_report(self, report_kind: str) -> ReportOut:
        result = self._reports.get_latest_report(report_kind)
        if result is None:
            raise SentinelHTTPException(
                code="REPORT_NOT_FOUND",
                message=f"no {report_kind!r} weekly report has been published yet",
                http_status=status.HTTP_404_NOT_FOUND,
            )
        report_key, body = result
        return ReportOut(retrieved_from_s3_key=report_key, body=body)

    def get_report_by_key(self, key: str) -> ReportOut:
        body = self._reports.get_report_by_key(key)
        if body is None:
            raise SentinelHTTPException(
                code="REPORT_NOT_FOUND",
                message=f"no report at key {key!r}",
                http_status=status.HTTP_404_NOT_FOUND,
            )
        return ReportOut(retrieved_from_s3_key=key, body=body)
