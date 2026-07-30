"""Unit tests for `functions/athena_curate_writes/handler.py` (phase-03
§5): the hourly curate query targets the correct 1-hour partition window
and write-event filter, and a failed/timed-out Athena execution surfaces
as a real exception rather than silently returning.

See `test_athena_bootstrap.py` for why this is loaded via `importlib`
instead of a shared pytest `pythonpath` entry (both function dirs define a
top-level `handler.py`).
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_HANDLER_PATH = (
    Path(__file__).resolve().parents[2] / "functions" / "athena_curate_writes" / "handler.py"
)
_spec = importlib.util.spec_from_file_location("athena_curate_writes_handler", _HANDLER_PATH)
assert _spec is not None and _spec.loader is not None
curate_handler = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = curate_handler
_spec.loader.exec_module(curate_handler)


@pytest.fixture(autouse=True)
def _mock_athena() -> MagicMock:
    with patch.object(curate_handler, "_athena") as mock:
        yield mock


def test_query_targets_the_prior_hours_partition_and_write_events(_mock_athena: MagicMock) -> None:
    _mock_athena.start_query_execution.return_value = {"QueryExecutionId": "q-1"}
    _mock_athena.get_query_execution.return_value = {
        "QueryExecution": {"Status": {"State": "SUCCEEDED"}}
    }

    curate_handler.run_curate_query(
        workgroup_name="sentinel",
        database_name="sentinel_cloudtrail",
        raw_table="cloudtrail_logs",
        curated_table="writes_curated",
        now=datetime(2026, 7, 30, 15, 30, tzinfo=UTC),
    )

    query = _mock_athena.start_query_execution.call_args.kwargs["QueryString"]
    assert "year = '2026' AND month = '07' AND day = '30'" in query
    assert "INSERT INTO sentinel_cloudtrail.writes_curated" in query
    assert "'PutObject'" in query


def test_failed_query_raises_with_the_state_change_reason(_mock_athena: MagicMock) -> None:
    _mock_athena.start_query_execution.return_value = {"QueryExecutionId": "q-2"}
    _mock_athena.get_query_execution.return_value = {
        "QueryExecution": {"Status": {"State": "FAILED", "StateChangeReason": "table not found"}}
    }

    with pytest.raises(RuntimeError, match="table not found"):
        curate_handler.run_curate_query(
            workgroup_name="sentinel",
            database_name="sentinel_cloudtrail",
            raw_table="cloudtrail_logs",
            curated_table="writes_curated",
        )


def test_handler_reads_configuration_from_environment(
    monkeypatch: pytest.MonkeyPatch, _mock_athena: MagicMock
) -> None:
    monkeypatch.setenv("ATHENA_WORKGROUP", "sentinel")
    monkeypatch.setenv("ATHENA_DATABASE", "sentinel_cloudtrail")
    monkeypatch.setenv("ATHENA_RAW_TABLE", "cloudtrail_logs")
    monkeypatch.setenv("ATHENA_CURATED_TABLE", "writes_curated")
    _mock_athena.start_query_execution.return_value = {"QueryExecutionId": "q-3"}
    _mock_athena.get_query_execution.return_value = {
        "QueryExecution": {"Status": {"State": "SUCCEEDED"}}
    }

    result = curate_handler.handler({}, object())

    assert result == {"QueryExecutionId": "q-3"}
