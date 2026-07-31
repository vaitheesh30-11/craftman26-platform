"""data_event_query — phase-04 §4 Step 3.

Moto's Athena backend accepts `StartQueryExecution`/`GetQueryExecution` but
has no real SQL engine behind it (it never actually executes the query
string against `cloudtrail_logs`), so `GetQueryResults` can't be seeded
with row data through moto alone. A minimal fake Athena client (injected
via `athena_client=`, the same injection point production skips in favor
of `cross_account.assume()`) stands in for "moto's Athena mock plus a
fixture result set" per the phase doc's own §8 Test Plan wording -- it
implements exactly the three calls `query_data_events` makes.
"""

from __future__ import annotations

from typing import Any

import pytest

from iam_sentinel_agents.tools.f3.query import query_data_events

pytestmark = pytest.mark.unit


class _FakeAthenaClient:
    def __init__(self, rows: list[list[str | None]]) -> None:
        self._rows = rows

    def start_query_execution(self, **_kwargs: Any) -> dict[str, str]:
        return {"QueryExecutionId": "q-1"}

    def get_query_execution(self, **_kwargs: Any) -> dict[str, Any]:
        return {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}}

    def get_paginator(self, operation_name: str) -> _FakeAthenaClient:
        assert operation_name == "get_query_results"
        return self

    def paginate(self, **_kwargs: Any) -> list[dict[str, Any]]:
        header = {
            "Data": [
                {"VarCharValue": name} for name in ("action", "bucket", "object_key", "call_count")
            ]
        }
        body = [{"Data": [{"VarCharValue": value} for value in row]} for row in self._rows]
        return [{"ResultSet": {"Rows": [header, *body]}}]


def test_query_groups_rows_by_action_and_bucket_with_consolidated_prefixes() -> None:
    athena = _FakeAthenaClient(
        rows=[
            ["GetObject", "reports", "2026/01/a.json", "5"],
            ["GetObject", "reports", "2026/02/b.json", "3"],
            ["PutObject", "reports", "2026/03/c.json", "1"],
        ]
    )

    result = query_data_events(
        "arn:aws:iam::111122223333:role/DataPipeline",
        30,
        correlation_id="c1",
        athena_client=athena,
    )

    assert result["rows_scanned"] == 3
    usage_by_action = {entry["action"]: entry for entry in result["usage"]}
    assert usage_by_action["s3:GetObject"]["call_count"] == 8
    assert usage_by_action["s3:GetObject"]["consolidated_prefix"] == "2026/*"
    assert usage_by_action["s3:PutObject"]["call_count"] == 1


def test_query_skips_rows_for_actions_outside_the_s3_data_event_set() -> None:
    athena = _FakeAthenaClient(rows=[["GetBucketPolicy", "reports", None, "1"]])

    result = query_data_events(
        "arn:aws:iam::111122223333:role/DataPipeline",
        30,
        correlation_id="c2",
        athena_client=athena,
    )

    assert result["usage"] == []
    assert result["rows_scanned"] == 1
