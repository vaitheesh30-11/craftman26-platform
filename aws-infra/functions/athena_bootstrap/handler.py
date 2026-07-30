"""CloudFormation custom-resource Lambda that runs the two one-shot
Athena/Glue setup steps aws-infra phase-03 §5 and §9 need before the
`sentinel` workgroup is usable:

1. Pre-flight check that the org CloudTrail bucket is readable from this
   account (phase-03 §9 risk mitigation: "deploy fails if the trail bucket
   is unreadable" -- this cannot be fully verified without a real dev
   account and an org trail bucket policy granting this account; see
   ADR 0009).
2. Idempotently create the Iceberg `writes_curated` table via an Athena
   `CREATE TABLE ... WITH (table_type='ICEBERG', ...)` statement, since
   Iceberg metadata bootstrapping needs an engine that understands the
   Iceberg spec -- CloudFormation's `AWS::Glue::Table` alone cannot do it.

`Delete` is a no-op: this custom resource never drops catalog objects.
"""

from __future__ import annotations

import json
import time
import urllib.request
from typing import Any

import boto3

_s3 = boto3.client("s3")
_glue = boto3.client("glue")
_athena = boto3.client("athena")

_POLL_INTERVAL_SECONDS = 2
_POLL_TIMEOUT_SECONDS = 120
_TERMINAL_STATES = {"SUCCEEDED", "FAILED", "CANCELLED"}


def _check_trail_bucket_readable(bucket_name: str) -> None:
    try:
        _s3.head_bucket(Bucket=bucket_name)
    except Exception as exc:
        raise RuntimeError(
            f"org CloudTrail bucket {bucket_name!r} is not readable from this account -- "
            "verify the bucket policy in the org CloudTrail account grants this account's "
            "principals (phase-03 §6, §9)"
        ) from exc


def _curated_table_exists(database_name: str, table_name: str) -> bool:
    try:
        _glue.get_table(DatabaseName=database_name, Name=table_name)
        return True
    except _glue.exceptions.EntityNotFoundException:
        return False


def _run_query_and_wait(query: str, *, workgroup_name: str, database_name: str) -> None:
    execution = _athena.start_query_execution(
        QueryString=query,
        QueryExecutionContext={"Database": database_name},
        WorkGroup=workgroup_name,
    )
    execution_id = execution["QueryExecutionId"]

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


def _create_curated_table_ddl(table_name: str, location: str) -> str:
    return (
        f"CREATE TABLE IF NOT EXISTS {table_name} ("
        "action string, bucket string, object_key string, call_count bigint, "
        "event_date date, account_id string, event_source string"
        ") "
        "PARTITIONED BY (event_date, account_id, event_source) "
        f"LOCATION '{location}' "
        "TBLPROPERTIES ('table_type'='ICEBERG', 'format'='parquet')"
    )


def route_request(
    request_type: str, properties: dict[str, Any], physical_id: str | None
) -> dict[str, Any]:
    """Pure dispatch, kept separate from `handler` for unit testing."""
    if request_type in ("Create", "Update"):
        _check_trail_bucket_readable(properties["TrailBucketName"])

        database_name = properties["DatabaseName"]
        table_name = properties["CuratedTableName"]
        if not _curated_table_exists(database_name, table_name):
            _run_query_and_wait(
                _create_curated_table_ddl(table_name, properties["CuratedLocation"]),
                workgroup_name=properties["WorkgroupName"],
                database_name=database_name,
            )
        return {"PhysicalResourceId": f"{database_name}.{table_name}"}

    if request_type == "Delete":
        return {"PhysicalResourceId": physical_id or "not-created"}

    raise ValueError(f"unsupported RequestType: {request_type!r}")


def handler(event: dict[str, Any], _context: object) -> None:
    try:
        result = route_request(
            event["RequestType"],
            event.get("ResourceProperties", {}),
            event.get("PhysicalResourceId"),
        )
        _send_response(event, "SUCCESS", result["PhysicalResourceId"], {})
    except Exception as exc:  # noqa: BLE001 -- CFN must always be signaled, even on failure.
        _send_response(
            event, "FAILED", event.get("PhysicalResourceId", "unknown"), {}, reason=str(exc)
        )


def _send_response(
    event: dict[str, Any], status: str, physical_id: str, data: dict[str, Any], *, reason: str = ""
) -> None:
    body = json.dumps(
        {
            "Status": status,
            "Reason": reason or "See CloudWatch logs",
            "PhysicalResourceId": physical_id,
            "StackId": event["StackId"],
            "RequestId": event["RequestId"],
            "LogicalResourceId": event["LogicalResourceId"],
            "Data": data,
        }
    ).encode("utf-8")
    request = urllib.request.Request(url=event["ResponseURL"], data=body, method="PUT")  # noqa: S310
    urllib.request.urlopen(request)  # noqa: S310
