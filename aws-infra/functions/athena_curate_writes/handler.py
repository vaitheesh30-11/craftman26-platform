"""Hourly Lambda `athena_curate_writes` (phase-03 §5). Triggered by an
EventBridge `rate(1 hour)` rule (wired in `AthenaStack._build_curate_function`),
it runs a CTAS-style `INSERT INTO` over the last hour of `cloudtrail_logs`
filtered to S3 write events and appends the result into the Iceberg
`writes_curated` table, so F4/F6 scan a small curated table instead of raw
CloudTrail logs.

Verifying an actual successful write against a deployed workgroup + a
populated org trail is deferred -- see ADR 0009 and the module docstring
in `iam_sentinel_infra.stacks.athena_stack`.
"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import boto3

_athena = boto3.client("athena")

_POLL_INTERVAL_SECONDS = 2
_POLL_TIMEOUT_SECONDS = 240
_TERMINAL_STATES = {"SUCCEEDED", "FAILED", "CANCELLED"}
_WRITE_EVENT_NAMES = (
    "PutObject",
    "DeleteObject",
    "CompleteMultipartUpload",
    "CopyObject",
)


def _insert_curated_writes_ddl(
    *, raw_table: str, curated_table: str, window_start: datetime
) -> str:
    year, month, day = (
        window_start.strftime("%Y"),
        window_start.strftime("%m"),
        window_start.strftime("%d"),
    )
    event_names = ", ".join(f"'{name}'" for name in _WRITE_EVENT_NAMES)
    return (
        # Built from a fixed event-name allowlist and stack-supplied database/table
        # names, never external input -- not a real injection surface.
        f"INSERT INTO {curated_table} "  # noqa: S608
        "SELECT "
        "eventname AS action, "
        "json_extract_scalar(requestparameters, '$.bucketName') AS bucket, "
        "json_extract_scalar(requestparameters, '$.key') AS object_key, "
        "COUNT(*) AS call_count, "
        f"DATE('{window_start.date().isoformat()}') AS event_date, "
        "recipientaccountid AS account_id, "
        "eventsource AS event_source "
        f"FROM {raw_table} "
        f"WHERE year = '{year}' AND month = '{month}' AND day = '{day}' "
        "AND eventsource = 's3.amazonaws.com' "
        f"AND eventname IN ({event_names}) "
        "GROUP BY 1, 2, 3, recipientaccountid, eventsource"
    )


def run_curate_query(
    *,
    workgroup_name: str,
    database_name: str,
    raw_table: str,
    curated_table: str,
    now: datetime | None = None,
) -> str:
    """Pure-ish orchestration (only the boto3 calls are side-effecting),
    kept separate from `handler` for unit testing without a Lambda event."""
    window_start = (now or datetime.now(UTC)) - timedelta(hours=1)
    query = _insert_curated_writes_ddl(
        raw_table=f"{database_name}.{raw_table}",
        curated_table=f"{database_name}.{curated_table}",
        window_start=window_start,
    )
    execution = _athena.start_query_execution(
        QueryString=query,
        QueryExecutionContext={"Database": database_name},
        WorkGroup=workgroup_name,
    )
    execution_id: str = execution["QueryExecutionId"]
    _wait_for_completion(execution_id)
    return execution_id


def _wait_for_completion(execution_id: str) -> None:
    deadline = time.monotonic() + _POLL_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        status = _athena.get_query_execution(QueryExecutionId=execution_id)["QueryExecution"][
            "Status"
        ]
        state = status["State"]
        if state in _TERMINAL_STATES:
            if state != "SUCCEEDED":
                reason = status.get("StateChangeReason", "no reason given")
                raise RuntimeError(f"Athena query {execution_id} ended in {state}: {reason}")
            return
        time.sleep(_POLL_INTERVAL_SECONDS)
    raise TimeoutError(
        f"Athena query {execution_id} did not finish within {_POLL_TIMEOUT_SECONDS}s"
    )


def handler(_event: dict[str, Any], _context: object) -> dict[str, str]:
    execution_id = run_curate_query(
        workgroup_name=os.environ["ATHENA_WORKGROUP"],
        database_name=os.environ["ATHENA_DATABASE"],
        raw_table=os.environ["ATHENA_RAW_TABLE"],
        curated_table=os.environ["ATHENA_CURATED_TABLE"],
    )
    return {"QueryExecutionId": execution_id}
