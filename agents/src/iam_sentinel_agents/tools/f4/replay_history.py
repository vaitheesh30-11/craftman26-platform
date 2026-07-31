"""scp_impact_replay_history -- phase-05 SS4 Step 3: replay 90 days of
successful write calls from CloudTrail via Athena, scoped to every account
reachable under the target OU/account.
"""

from __future__ import annotations

import random
import time
from datetime import datetime, timedelta, UTC
from typing import Any, TYPE_CHECKING

import boto3

from iam_sentinel_agents.errors import SentinelAgentError
from iam_sentinel_agents.settings import settings
from iam_sentinel_agents.tools.common.runtime import sentinel_handler
from iam_sentinel_agents.tools.common.service_prefixes import canonicalize_action, is_write_action

if TYPE_CHECKING:
    from aws_lambda_powertools.utilities.typing import LambdaContext
    from mypy_boto3_athena.client import AthenaClient
    from mypy_boto3_organizations.client import OrganizationsClient

    from iam_sentinel_agents.tools.common.event_parser import ParsedInvocation

_ROW_CAP = 500_000
_TERMINAL_STATES = frozenset({"SUCCEEDED", "FAILED", "CANCELLED"})
_ACCOUNT_ID_LENGTH = 12


class AthenaQueryFailedError(SentinelAgentError):
    def __init__(self, query_execution_id: str, reason: str) -> None:
        super().__init__(f"Athena query {query_execution_id} did not succeed: {reason}")
        self.query_execution_id = query_execution_id


def _is_account_id(target: str) -> bool:
    return len(target) == _ACCOUNT_ID_LENGTH and target.isdigit()


def _accounts_under(org_client: OrganizationsClient, parent_id: str) -> list[str]:
    """`organizations:ListAccountsForParent` only returns the parent's
    *direct* child accounts, so nested OUs are walked recursively to
    collect every account beneath `parent_id` (phase-05 SS4 Step 3).
    """
    accounts = [
        account["Id"]
        for page in org_client.get_paginator("list_accounts_for_parent").paginate(
            ParentId=parent_id
        )
        for account in page["Accounts"]
    ]
    for page in org_client.get_paginator("list_organizational_units_for_parent").paginate(
        ParentId=parent_id
    ):
        for ou in page["OrganizationalUnits"]:
            accounts.extend(_accounts_under(org_client, ou["Id"]))
    return accounts


def accounts_for_target(org_client: OrganizationsClient, target: str) -> list[str]:
    if _is_account_id(target):
        return [target]
    return _accounts_under(org_client, target)


def build_replay_query(account_ids: list[str], days_back: int) -> str:
    threshold = (datetime.now(UTC) - timedelta(days=days_back)).strftime("%Y%m%d")
    account_list = ", ".join(f"'{account_id}'" for account_id in account_ids)
    # account_ids come from `organizations:List*` (12-digit ids only, never
    # free-text user input) and `threshold` is derived from `datetime.now()`
    # -- there is no untrusted input reaching this string.
    return (
        "SELECT useridentity.arn AS role_arn, eventsource, eventname, COUNT(*) AS call_count "  # noqa: S608
        "FROM sentinel_cloudtrail.cloudtrail_logs "
        f"WHERE account_id IN ({account_list}) "
        "AND (errorcode IS NULL OR errorcode = '') "
        "AND readonly = false "
        f"AND year || month || day >= '{threshold}' "
        "GROUP BY 1, 2, 3"
    )


def _poll_until_terminal(
    athena_client: AthenaClient,
    query_execution_id: str,
    *,
    poll_interval_seconds: float,
    max_polls: int,
) -> None:
    for _ in range(max_polls):
        status = athena_client.get_query_execution(QueryExecutionId=query_execution_id)[
            "QueryExecution"
        ]["Status"]
        state = status["State"]
        if state in _TERMINAL_STATES:
            if state != "SUCCEEDED":
                raise AthenaQueryFailedError(
                    query_execution_id, status.get("StateChangeReason", state)
                )
            return
        time.sleep(poll_interval_seconds)
    raise AthenaQueryFailedError(query_execution_id, "timed out waiting for a terminal state")


def _rows_from_results(
    athena_client: AthenaClient, query_execution_id: str
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    header_skipped = False
    for page in athena_client.get_paginator("get_query_results").paginate(
        QueryExecutionId=query_execution_id
    ):
        for row in page["ResultSet"]["Rows"]:
            values = [cell.get("VarCharValue") for cell in row["Data"]]
            if not header_skipped:
                header_skipped = True
                continue
            role_arn, event_source, event_name, call_count = values
            rows.append(
                {
                    "role_arn": role_arn,
                    "event_source": event_source,
                    "event_name": event_name,
                    "call_count": int(call_count or 0),
                }
            )
    return rows


def run_replay_query(
    athena_client: AthenaClient,
    query: str,
    *,
    database: str,
    output_location: str,
    poll_interval_seconds: float = 0.5,
    max_polls: int = 120,
) -> list[dict[str, Any]]:
    started = athena_client.start_query_execution(
        QueryString=query,
        QueryExecutionContext={"Database": database},
        ResultConfiguration={"OutputLocation": output_location},
    )
    query_execution_id = started["QueryExecutionId"]
    _poll_until_terminal(
        athena_client,
        query_execution_id,
        poll_interval_seconds=poll_interval_seconds,
        max_polls=max_polls,
    )
    return _rows_from_results(athena_client, query_execution_id)


def sample_rows(
    rows: list[dict[str, Any]], *, cap: int = _ROW_CAP, seed: int | None = None
) -> tuple[list[dict[str, Any]], bool, int]:
    """Uniform sampling with a recorded seed for reproducibility (phase-05
    SS9 acceptance: "Sampled runs are labeled and reproducible via a
    recorded sample seed"). Returns `(rows, sampled, seed_used)`.
    """
    if len(rows) <= cap:
        return rows, False, seed if seed is not None else 0
    resolved_seed = seed if seed is not None else 0
    # Reproducible, uniform sampling of a bounded data set -- not a security
    # or cryptographic use of randomness.
    return random.Random(resolved_seed).sample(rows, cap), True, resolved_seed  # noqa: S311


def replay_history(
    target: str,
    *,
    org_client: OrganizationsClient,
    athena_client: AthenaClient,
    days_back: int = 90,
    database: str | None = None,
    output_location: str | None = None,
    sample_seed: int | None = None,
) -> dict[str, Any]:
    """Core replay logic, independent of the Bedrock Lambda envelope.
    `org_client`/`athena_client` are the injection points tests use.
    """
    account_ids = accounts_for_target(org_client, target)
    query = build_replay_query(account_ids, days_back)
    raw_rows = run_replay_query(
        athena_client,
        query,
        database=database or settings.athena_database,
        output_location=output_location or settings.athena_output_location,
    )
    write_rows = [row for row in raw_rows if row["role_arn"] and is_write_action(row["event_name"])]
    sampled_rows, sampled, seed = sample_rows(write_rows, seed=sample_seed)
    history = [
        {
            "role_arn": row["role_arn"],
            "event_source": row["event_source"],
            "event_name": row["event_name"],
            "action": canonicalize_action(row["event_source"], row["event_name"]),
            "call_count": row["call_count"],
        }
        for row in sampled_rows
    ]
    return {
        "history": history,
        "accounts_scanned": len(account_ids),
        "total_calls_analyzed": sum(row["call_count"] for row in history),
        "sampled": sampled,
        "sample_seed": seed,
    }


@sentinel_handler(feature_id="F4", tool_name="scp_impact_replay_history")
def scp_impact_replay_history(
    invocation: ParsedInvocation, _context: LambdaContext
) -> dict[str, Any]:
    target = invocation.parameters["target"]
    days_back = int(invocation.parameters.get("days_back", 90))
    org: OrganizationsClient = boto3.client("organizations", region_name=settings.region)
    athena: AthenaClient = boto3.client("athena", region_name=settings.region)
    return replay_history(target, org_client=org, athena_client=athena, days_back=days_back)
