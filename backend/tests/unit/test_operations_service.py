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


def _service(
    *,
    faults_client: object | None = None,
    reports_client: object | None = None,
    divergence_client: object | None = None,
    breaker_accessor: object | None = None,
    dlq_client: object | None = None,
) -> OperationsService:
    return OperationsService(
        faults_client or MagicMock(),
        reports_client or MagicMock(),
        divergence_client or MagicMock(),
        breaker_accessor or MagicMock(),
        dlq_client or MagicMock(),
    )


def _divergence(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "correlation_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
        "feature_id": "F1",
        "input_hash": "deadbeef",
        "divergence_kind": "material_disagreement",
        "diff_summary": "fast path missed an edge",
        "reviewed": False,
        "detected_at": "2026-07-30T00:00:00+00:00",
    }
    base.update(overrides)
    return base


def test_list_faults_returns_a_page() -> None:
    faults_client = MagicMock()
    faults_client.list_recent.return_value = ([_fault()], None)
    service = _service(faults_client=faults_client)

    page = service.list_faults()

    assert len(page.items) == 1
    assert page.next_token is None


def test_latest_cost_report_returns_404_when_none_published() -> None:
    reports_client = MagicMock()
    reports_client.get_latest_cost_report.return_value = None
    service = _service(reports_client=reports_client)

    with pytest.raises(SentinelHTTPException) as exc_info:
        service.latest_cost_report()

    assert exc_info.value.status_code == 404


def test_latest_cost_report_wraps_the_key_and_body() -> None:
    reports_client = MagicMock()
    reports_client.get_latest_cost_report.return_value = ("cost/2026-W30.json", {"total_usd": 12.5})
    service = _service(reports_client=reports_client)

    result = service.latest_cost_report()

    assert result.report_key == "cost/2026-W30.json"
    assert result.body == {"total_usd": 12.5}


def test_list_divergence_returns_a_page() -> None:
    divergence_client = MagicMock()
    divergence_client.list_recent.return_value = ([_divergence()], None)
    service = _service(divergence_client=divergence_client)

    page = service.list_divergence(feature_id="F1")

    assert len(page.items) == 1
    assert page.items[0].divergence_kind == "material_disagreement"
    assert page.next_token is None


def test_get_health_composes_breaker_and_dlq_state() -> None:
    breaker_accessor = MagicMock()
    breaker_accessor.state.return_value = "open"
    dlq_client = MagicMock()
    dlq_client.get_depth.return_value = 3
    service = _service(breaker_accessor=breaker_accessor, dlq_client=dlq_client)

    snapshot = service.get_health()

    assert len(snapshot.breakers) > 0
    assert all(breaker.state == "open" for breaker in snapshot.breakers)
    # `AdapterSettings.dlq_queue_urls` defaults empty (ADR 0023) -- no
    # deployed queue URL registry to read from yet.
    assert snapshot.dlqs == []
