"""data_event_query — phase-04 §4 Step 3: Athena over CloudTrail S3 data
events.

Calls boto3 Athena APIs directly via `cross_account.assume()`'s returned
session, same deliberate exception documented in `ensure_logging.py`'s and
`tools/f1/scan.py`'s module docstrings.

Workgroup name: aws-infra ADR 0009 reconciled this phase doc's own
`sentinel-f3` (§Step 2) to aws-infra phase-03's `sentinel` -- this module
uses the reconciled name, not the phase doc's original literal string, per
that ADR's own note that this reconciliation was still open until agents
phase-04 landed.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, UTC
from typing import Any, cast, TYPE_CHECKING

from iam_sentinel_agents.contracts.data_event import S3DataEventAction, S3DataEventUsage
from iam_sentinel_agents.settings import settings
from iam_sentinel_agents.tools.common import cross_account
from iam_sentinel_agents.tools.common.runtime import sentinel_handler
from iam_sentinel_agents.tools.f3.consolidate import consolidate_prefix

if TYPE_CHECKING:
    import boto3
    from aws_lambda_powertools.utilities.typing import LambdaContext
    from mypy_boto3_athena.client import AthenaClient

    from iam_sentinel_agents.contracts.common import FeatureID
    from iam_sentinel_agents.tools.common.event_parser import ParsedInvocation

_WORKGROUP = "sentinel"
_DATABASE = "sentinel_cloudtrail"
_TABLE = "cloudtrail_logs"
_CLOUDTRAIL_ACTION_NAMES = (
    "GetObject",
    "PutObject",
    "DeleteObject",
    "ListMultipartUploadParts",
    "AbortMultipartUpload",
)
_VALID_USAGE_ACTIONS: frozenset[str] = frozenset(f"s3:{name}" for name in _CLOUDTRAIL_ACTION_NAMES)
_MAX_ROWS = 100_000
_POLL_INTERVAL_SECONDS = 1.0
_MAX_POLLS = 60


def _build_query(role_arn: str, days_back: int) -> str:
    since = datetime.now(UTC) - timedelta(days=days_back)
    # Athena has no bind-parameter API reachable through boto3's
    # StartQueryExecution -- the phase doc's `?` placeholders are
    # illustrative, not literal. `role_arn` is escaped (single-quote
    # doubling, the standard SQL escape) rather than passed unescaped.
    safe_role_arn = role_arn.replace("'", "''")
    action_list = ", ".join(f"'{name}'" for name in _CLOUDTRAIL_ACTION_NAMES)
    # Athena has no bind-parameter path through boto3's StartQueryExecution;
    # `safe_role_arn` is escaped above (single-quote doubling), and
    # `_DATABASE`/`_TABLE`/`action_list`/the year/month fields are all
    # module constants or zero-padded ints -- never untrusted free text.
    query = (
        "SELECT eventname AS action, "  # noqa: S608
        "json_extract_scalar(requestparameters, '$.bucketName') AS bucket, "
        "json_extract_scalar(requestparameters, '$.key') AS object_key, "
        "COUNT(*) AS call_count "
        f"FROM {_DATABASE}.{_TABLE} "
        f"WHERE useridentity.arn = '{safe_role_arn}' "
        "AND eventsource = 's3.amazonaws.com' "
        f"AND eventname IN ({action_list}) "
        f"AND year >= '{since.year:04d}' AND month >= '{since.month:02d}' "
        "GROUP BY 1, 2, 3"
    )
    return query


def _wait_for_completion(athena: AthenaClient, query_execution_id: str) -> None:
    for _ in range(_MAX_POLLS):
        execution = athena.get_query_execution(QueryExecutionId=query_execution_id)[
            "QueryExecution"
        ]
        state = execution["Status"]["State"]
        if state == "SUCCEEDED":
            return
        if state in ("FAILED", "CANCELLED"):
            reason = execution["Status"].get("StateChangeReason", "")
            raise RuntimeError(
                f"Athena query {query_execution_id} ended in state {state}: {reason}"
            )
        time.sleep(_POLL_INTERVAL_SECONDS)
    raise TimeoutError(f"Athena query {query_execution_id} did not complete in time")


def _fetch_rows(athena: AthenaClient, query_execution_id: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    header: list[str] | None = None
    paginator = athena.get_paginator("get_query_results")
    for page in paginator.paginate(QueryExecutionId=query_execution_id):
        for row in page["ResultSet"]["Rows"]:
            values = [cell.get("VarCharValue") or "" for cell in row["Data"]]
            if header is None:
                header = values
                continue
            rows.append(dict(zip(header, values, strict=False)))
            if len(rows) >= _MAX_ROWS:
                return rows
    return rows


def _group_rows(raw_rows: list[dict[str, str]]) -> list[S3DataEventUsage]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in raw_rows:
        action = f"s3:{row.get('action', '')}"
        if action not in _VALID_USAGE_ACTIONS:
            continue
        bucket = row.get("bucket") or ""
        if not bucket:
            continue
        object_key = row.get("object_key") or ""
        call_count = int(row.get("call_count") or 0)
        entry = grouped.setdefault((action, bucket), {"prefixes": [], "call_count": 0})
        if object_key:
            entry["prefixes"].append(object_key)
        entry["call_count"] += call_count

    usage: list[S3DataEventUsage] = []
    for (action, bucket), entry in grouped.items():
        consolidated_prefix, _bucket_wide_warning = consolidate_prefix(entry["prefixes"])
        usage.append(
            S3DataEventUsage(
                action=cast("S3DataEventAction", action),
                bucket=bucket,
                prefixes=sorted(set(entry["prefixes"])),
                consolidated_prefix=consolidated_prefix,
                call_count=entry["call_count"],
            )
        )
    return usage


def query_data_events(
    role_arn: str,
    days_back: int = 30,
    *,
    account_id: str | None = None,
    output_location: str | None = None,
    feature_id: FeatureID = "F3",
    correlation_id: str = "data-event-query",
    session: boto3.Session | None = None,
    athena_client: AthenaClient | None = None,
) -> dict[str, Any]:
    """Core logic, independent of the Bedrock Lambda envelope.

    `athena_client`/`session` are injection points for tests -- production
    always resolves an Athena client through `cross_account.assume()`.
    """
    if athena_client is not None:
        athena: AthenaClient = athena_client
    else:
        resolved_account_id = account_id or role_arn.split(":")[4]
        boto_session = session or cross_account.assume(
            resolved_account_id, feature_id=feature_id, correlation_id=correlation_id
        )
        athena = boto_session.client("athena")

    query = _build_query(role_arn, days_back)
    execution = athena.start_query_execution(
        QueryString=query,
        QueryExecutionContext={"Database": _DATABASE},
        WorkGroup=_WORKGROUP,
        ResultConfiguration={"OutputLocation": output_location or settings.athena_output_location},
    )
    query_execution_id = execution["QueryExecutionId"]
    _wait_for_completion(athena, query_execution_id)
    raw_rows = _fetch_rows(athena, query_execution_id)
    usage = _group_rows(raw_rows)

    return {
        "usage": [entry.model_dump(mode="json") for entry in usage],
        "rows_scanned": len(raw_rows),
    }


@sentinel_handler(feature_id="F3", tool_name="data_event_query")
def data_event_query(invocation: ParsedInvocation, _context: LambdaContext) -> dict[str, Any]:
    return query_data_events(
        invocation.parameters["role_arn"],
        int(invocation.parameters.get("days_back", 30)),
        correlation_id=invocation.correlation_id,
    )
