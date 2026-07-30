from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from iam_sentinel_backend.errors import SentinelHTTPException
from iam_sentinel_backend.services.operations_service import OperationsService


def _fault(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "correlation_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
        "fault_class": "transient_throttling",
        "origin": "FindingsClient",
        "action_taken": "retried",
        "detail": "detail",
        "detected_at": "2026-07-30T00:00:00+00:00",
    }
    base.update(overrides)
    return base


def test_list_faults_returns_a_page() -> None:
    faults_client = MagicMock()
    faults_client.list_recent.return_value = ([_fault()], None)
    service = OperationsService(faults_client, MagicMock())

    page = service.list_faults()

    assert len(page.items) == 1
    assert page.next_token is None


def test_latest_cost_report_returns_404_when_none_published() -> None:
    reports_client = MagicMock()
    reports_client.get_latest_cost_report.return_value = None
    service = OperationsService(MagicMock(), reports_client)

    with pytest.raises(SentinelHTTPException) as exc_info:
        service.latest_cost_report()

    assert exc_info.value.status_code == 404


def test_latest_cost_report_wraps_the_key_and_body() -> None:
    reports_client = MagicMock()
    reports_client.get_latest_cost_report.return_value = ("cost/2026-W30.json", {"total_usd": 12.5})
    service = OperationsService(MagicMock(), reports_client)

    result = service.latest_cost_report()

    assert result.report_key == "cost/2026-W30.json"
    assert result.body == {"total_usd": 12.5}
