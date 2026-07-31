from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from iam_sentinel_backend.errors import SentinelHTTPException
from iam_sentinel_backend.services.reports_service import ReportsService


def test_latest_weekly_report_resolves_the_latest_key_and_body() -> None:
    reports_client = MagicMock()
    reports_client.get_latest_report.return_value = ("f6/2026-W30.json", {"violations": 3})
    service = ReportsService(reports_client)

    result = service.latest_weekly_report("f6")

    reports_client.get_latest_report.assert_called_once_with("f6")
    assert result.retrieved_from_s3_key == "f6/2026-W30.json"
    assert result.body == {"violations": 3}


def test_latest_weekly_report_returns_404_when_none_published() -> None:
    reports_client = MagicMock()
    reports_client.get_latest_report.return_value = None
    service = ReportsService(reports_client)

    with pytest.raises(SentinelHTTPException) as exc_info:
        service.latest_weekly_report("cost")

    assert exc_info.value.status_code == 404


def test_get_report_by_key_returns_the_exact_key() -> None:
    reports_client = MagicMock()
    reports_client.get_report_by_key.return_value = {"ok": True}
    service = ReportsService(reports_client)

    result = service.get_report_by_key("f2/2026-W01.json")

    assert result.retrieved_from_s3_key == "f2/2026-W01.json"
    assert result.body == {"ok": True}


def test_get_report_by_key_returns_404_when_missing() -> None:
    reports_client = MagicMock()
    reports_client.get_report_by_key.return_value = None
    service = ReportsService(reports_client)

    with pytest.raises(SentinelHTTPException) as exc_info:
        service.get_report_by_key("f2/missing.json")

    assert exc_info.value.status_code == 404
