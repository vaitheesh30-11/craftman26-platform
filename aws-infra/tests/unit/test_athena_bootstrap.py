"""Unit tests for `functions/athena_bootstrap/handler.py` (phase-03 §5, §9):
the trail-bucket pre-flight check fails early, and the Iceberg curated
table is only created when it doesn't already exist.

Loaded via `importlib` from its file path rather than a shared pytest
`pythonpath` entry: `athena_curate_writes/handler.py` also defines a
top-level `handler.py`, and adding both directories to `pythonpath` would
make `import handler` resolve to whichever module Python cached first --
the same `handler.py`-name collision noted in aws-infra phase-02's mypy fix
(EXECUTION_STATE.txt HISTORY), just hitting pytest's import machinery
instead of mypy's.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_HANDLER_PATH = (
    Path(__file__).resolve().parents[2] / "functions" / "athena_bootstrap" / "handler.py"
)
_spec = importlib.util.spec_from_file_location("athena_bootstrap_handler", _HANDLER_PATH)
assert _spec is not None and _spec.loader is not None
bootstrap_handler = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = bootstrap_handler
_spec.loader.exec_module(bootstrap_handler)

_PROPERTIES = {
    "WorkgroupName": "sentinel",
    "DatabaseName": "sentinel_cloudtrail",
    "CuratedTableName": "writes_curated",
    "CuratedLocation": "s3://sentinel-reports-dev-111111111111/athena-curated/writes_curated/",
    "TrailBucketName": "org-cloudtrail-bucket-dev-placeholder",
}


@pytest.fixture(autouse=True)
def _mock_clients() -> tuple[MagicMock, MagicMock, MagicMock]:
    with (
        patch.object(bootstrap_handler, "_s3") as s3,
        patch.object(bootstrap_handler, "_glue") as glue,
        patch.object(bootstrap_handler, "_athena") as athena,
    ):
        glue.exceptions.EntityNotFoundException = type("EntityNotFoundException", (Exception,), {})
        yield s3, glue, athena


def test_unreadable_trail_bucket_fails_the_deploy_early(
    _mock_clients: tuple[MagicMock, MagicMock, MagicMock],
) -> None:
    s3, _glue, _athena = _mock_clients
    s3.head_bucket.side_effect = Exception("403 Forbidden")

    with pytest.raises(RuntimeError, match="not readable"):
        bootstrap_handler.route_request("Create", _PROPERTIES, physical_id=None)


def test_existing_curated_table_is_left_alone(
    _mock_clients: tuple[MagicMock, MagicMock, MagicMock],
) -> None:
    _s3, glue, athena = _mock_clients
    glue.get_table.return_value = {"Table": {"Name": "writes_curated"}}

    result = bootstrap_handler.route_request("Create", _PROPERTIES, physical_id=None)

    athena.start_query_execution.assert_not_called()
    assert result["PhysicalResourceId"] == "sentinel_cloudtrail.writes_curated"


def test_missing_curated_table_is_created_via_athena_ddl(
    _mock_clients: tuple[MagicMock, MagicMock, MagicMock],
) -> None:
    _s3, glue, athena = _mock_clients
    glue.get_table.side_effect = glue.exceptions.EntityNotFoundException()
    athena.start_query_execution.return_value = {"QueryExecutionId": "q-1"}
    athena.get_query_execution.return_value = {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}}

    bootstrap_handler.route_request("Create", _PROPERTIES, physical_id=None)

    ddl = athena.start_query_execution.call_args.kwargs["QueryString"]
    assert "table_type'='ICEBERG'" in ddl
    assert "writes_curated" in ddl


def test_failed_query_execution_raises(
    _mock_clients: tuple[MagicMock, MagicMock, MagicMock],
) -> None:
    _s3, glue, athena = _mock_clients
    glue.get_table.side_effect = glue.exceptions.EntityNotFoundException()
    athena.start_query_execution.return_value = {"QueryExecutionId": "q-2"}
    athena.get_query_execution.return_value = {
        "QueryExecution": {"Status": {"State": "FAILED", "StateChangeReason": "syntax error"}}
    }

    with pytest.raises(RuntimeError, match="syntax error"):
        bootstrap_handler.route_request("Create", _PROPERTIES, physical_id=None)


def test_delete_is_a_noop(_mock_clients: tuple[MagicMock, MagicMock, MagicMock]) -> None:
    _s3, _glue, athena = _mock_clients

    result = bootstrap_handler.route_request(
        "Delete", {}, physical_id="sentinel_cloudtrail.writes_curated"
    )

    athena.start_query_execution.assert_not_called()
    assert result["PhysicalResourceId"] == "sentinel_cloudtrail.writes_curated"
