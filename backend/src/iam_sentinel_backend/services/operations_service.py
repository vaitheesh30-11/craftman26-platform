"""`GET /operations/faults`, `GET /operations/cost/weekly`, `GET
/operations/divergence`, `GET /operations/health` (backend phase-01 §7,
phase-04 §2/§4 step 2). No access-control scoping per the spec -- all four
are operator-facing observability views, not principal-scoped data.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import status
from iam_sentinel_adapters.settings import settings as adapter_settings

from iam_sentinel_backend.errors import SentinelHTTPException
from iam_sentinel_backend.pagination import (
    clamp_limit,
    decode_next_token,
    encode_next_token,
    InvalidNextTokenError,
)
from iam_sentinel_backend.schemas.operations import (
    BreakerStateOut,
    CostReportOut,
    DivergencePage,
    DivergenceRecordOut,
    DlqDepthOut,
    FaultRecordOut,
    FaultsPage,
    HealthSnapshotOut,
)

if TYPE_CHECKING:
    from datetime import datetime

    from iam_sentinel_adapters.circuit_breaker import BreakerAccessor
    from iam_sentinel_adapters.ddb.divergence import DivergenceClient
    from iam_sentinel_adapters.ddb.faults import FaultsClient
    from iam_sentinel_adapters.s3.reports import ReportsClient
    from iam_sentinel_adapters.sqs.dlq import DlqClient


def _parse_csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


class OperationsService:
    def __init__(
        self,
        faults_client: FaultsClient,
        reports_client: ReportsClient,
        divergence_client: DivergenceClient,
        breaker_accessor: BreakerAccessor,
        dlq_client: DlqClient,
    ) -> None:
        self._faults = faults_client
        self._reports = reports_client
        self._divergence = divergence_client
        self._breakers = breaker_accessor
        self._dlq = dlq_client

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

    def list_divergence(
        self,
        *,
        feature_id: str | None = None,
        divergence_kind: str | None = None,
        since: datetime | None = None,
        limit: int = 25,
        next_token: str | None = None,
    ) -> DivergencePage:
        try:
            exclusive_start_key = decode_next_token(next_token)
        except InvalidNextTokenError as exc:
            raise SentinelHTTPException(
                code="INVALID_NEXT_TOKEN", message=str(exc), http_status=status.HTTP_400_BAD_REQUEST
            ) from exc

        items, last_key = self._divergence.list_recent(
            feature_id=feature_id,
            divergence_kind=divergence_kind,
            since=since,
            limit=clamp_limit(limit),
            exclusive_start_key=exclusive_start_key,
        )
        return DivergencePage(
            items=[DivergenceRecordOut.model_validate(item) for item in items],
            next_token=encode_next_token(last_key),
        )

    def get_health(self) -> HealthSnapshotOut:
        """Composite health snapshot (backend phase-04 §2/§4 step 2):
        breaker states for every settings-configured breaker name, plus
        approximate DLQ depths for every settings-configured queue URL.
        Neither list is discovered at runtime -- see
        `AdapterSettings.known_breaker_names`/`dlq_queue_urls` and ADR 0023.
        """
        breaker_names = _parse_csv(adapter_settings.known_breaker_names)
        dlq_urls = _parse_csv(adapter_settings.dlq_queue_urls)
        return HealthSnapshotOut(
            breakers=[
                BreakerStateOut(breaker_name=name, state=self._breakers.state(name))
                for name in breaker_names
            ],
            dlqs=[
                DlqDepthOut(queue_url=url, approximate_messages=self._dlq.get_depth(url))
                for url in dlq_urls
            ],
        )
