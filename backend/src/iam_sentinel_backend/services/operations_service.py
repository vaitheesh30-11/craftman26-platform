"""`GET /operations/faults`, `GET /operations/cost/weekly` (backend
phase-01 §7). No access-control scoping per the spec -- both are
operator-facing observability views, not principal-scoped data.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import status

from iam_sentinel_backend.errors import SentinelHTTPException
from iam_sentinel_backend.pagination import (
    clamp_limit,
    decode_next_token,
    encode_next_token,
    InvalidNextTokenError,
)
from iam_sentinel_backend.schemas.operations import CostReportOut, FaultRecordOut, FaultsPage

if TYPE_CHECKING:
    from datetime import datetime

    from iam_sentinel_adapters.ddb.faults import FaultsClient
    from iam_sentinel_adapters.s3.reports import ReportsClient


class OperationsService:
    def __init__(self, faults_client: FaultsClient, reports_client: ReportsClient) -> None:
        self._faults = faults_client
        self._reports = reports_client

    def list_faults(
        self,
        *,
        fault_class: str | None = None,
        since: datetime | None = None,
        limit: int = 25,
        next_token: str | None = None,
    ) -> FaultsPage:
        try:
            exclusive_start_key = decode_next_token(next_token)
        except InvalidNextTokenError as exc:
            raise SentinelHTTPException(
                code="INVALID_NEXT_TOKEN", message=str(exc), http_status=status.HTTP_400_BAD_REQUEST
            ) from exc

        items, last_key = self._faults.list_recent(
            fault_class=fault_class,
            since=since,
            limit=clamp_limit(limit),
            exclusive_start_key=exclusive_start_key,
        )
        return FaultsPage(
            items=[FaultRecordOut.model_validate(item) for item in items],
            next_token=encode_next_token(last_key),
        )

    def latest_cost_report(self) -> CostReportOut:
        result = self._reports.get_latest_cost_report()
        if result is None:
            raise SentinelHTTPException(
                code="COST_REPORT_NOT_FOUND",
                message="no cost report has been published yet",
                http_status=status.HTTP_404_NOT_FOUND,
            )
        report_key, body = result
        return CostReportOut(report_key=report_key, body=body)
