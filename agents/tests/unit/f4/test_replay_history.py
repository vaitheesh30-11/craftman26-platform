from __future__ import annotations

from unittest.mock import MagicMock

import boto3
import pytest
from moto import mock_aws

from iam_sentinel_agents.tools.f4 import replay_history

pytestmark = pytest.mark.unit


def _athena_row(*values: str) -> dict[str, object]:
    return {"Data": [{"VarCharValue": v} for v in values]}


def test_build_replay_query_includes_every_account_and_the_write_filters() -> None:
    query = replay_history.build_replay_query(["111111111111", "222222222222"], 90)
    assert "'111111111111'" in query
    assert "'222222222222'" in query
    assert "readonly = false" in query


@mock_aws
def test_accounts_for_target_recurses_through_nested_ous() -> None:
    org = boto3.client("organizations", region_name="us-east-1")
    org.create_organization(FeatureSet="ALL")
    root_id = org.list_roots()["Roots"][0]["Id"]
    parent_ou = org.create_organizational_unit(ParentId=root_id, Name="Parent")[
        "OrganizationalUnit"
    ]
    child_ou = org.create_organizational_unit(ParentId=parent_ou["Id"], Name="Child")[
        "OrganizationalUnit"
    ]
    account_id = org.create_account(Email="a@b.com", AccountName="acct1")["CreateAccountStatus"][
        "AccountId"
    ]
    org.move_account(
        AccountId=account_id, SourceParentId=root_id, DestinationParentId=child_ou["Id"]
    )

    accounts = replay_history.accounts_for_target(org, parent_ou["Id"])

    assert account_id in accounts


def test_accounts_for_target_returns_the_account_itself_for_an_account_id() -> None:
    assert replay_history.accounts_for_target(MagicMock(), "123456789012") == ["123456789012"]


def test_sample_rows_leaves_small_row_sets_untouched() -> None:
    rows = [{"a": i} for i in range(3)]
    sampled, was_sampled, _seed = replay_history.sample_rows(rows, cap=5)
    assert sampled == rows
    assert was_sampled is False


def test_sample_rows_caps_and_labels_large_row_sets_reproducibly() -> None:
    rows = [{"a": i} for i in range(10)]
    first, was_sampled, seed = replay_history.sample_rows(rows, cap=4, seed=7)
    second, _, _ = replay_history.sample_rows(rows, cap=4, seed=7)
    assert was_sampled is True
    assert len(first) == 4
    assert seed == 7
    assert first == second


def test_run_replay_query_parses_rows_and_skips_the_header() -> None:
    athena = MagicMock()
    athena.start_query_execution.return_value = {"QueryExecutionId": "q-1"}
    athena.get_query_execution.return_value = {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}}
    athena.get_paginator.return_value.paginate.return_value = [
        {
            "ResultSet": {
                "Rows": [
                    _athena_row("role_arn", "eventsource", "eventname", "call_count"),
                    _athena_row(
                        "arn:aws:iam::111122223333:role/Deployer",
                        "s3.amazonaws.com",
                        "PutBucketPolicy",
                        "42",
                    ),
                ]
            }
        }
    ]

    rows = replay_history.run_replay_query(
        athena, "SELECT 1", database="db", output_location="s3://bucket/"
    )

    assert rows == [
        {
            "role_arn": "arn:aws:iam::111122223333:role/Deployer",
            "event_source": "s3.amazonaws.com",
            "event_name": "PutBucketPolicy",
            "call_count": 42,
        }
    ]


def test_run_replay_query_raises_on_a_failed_execution() -> None:
    athena = MagicMock()
    athena.start_query_execution.return_value = {"QueryExecutionId": "q-2"}
    athena.get_query_execution.return_value = {
        "QueryExecution": {"Status": {"State": "FAILED", "StateChangeReason": "syntax error"}}
    }

    with pytest.raises(replay_history.AthenaQueryFailedError):
        replay_history.run_replay_query(
            athena, "SELECT 1", database="db", output_location="s3://bucket/"
        )


@mock_aws
def test_run_replay_query_against_a_real_but_empty_moto_athena_backend() -> None:
    athena = boto3.client("athena", region_name="us-east-1")
    rows = replay_history.run_replay_query(
        athena, "SELECT 1", database="db", output_location="s3://bucket/path/"
    )
    assert rows == []


def test_replay_history_end_to_end_filters_reads_and_canonicalizes_actions() -> None:
    org = MagicMock()
    athena = MagicMock()
    athena.start_query_execution.return_value = {"QueryExecutionId": "q-3"}
    athena.get_query_execution.return_value = {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}}
    athena.get_paginator.return_value.paginate.return_value = [
        {
            "ResultSet": {
                "Rows": [
                    _athena_row("role_arn", "eventsource", "eventname", "call_count"),
                    _athena_row(
                        "arn:aws:iam::111122223333:role/Deployer",
                        "s3.amazonaws.com",
                        "PutBucketPolicy",
                        "10",
                    ),
                    _athena_row(
                        "arn:aws:iam::111122223333:role/Reader",
                        "s3.amazonaws.com",
                        "GetObject",
                        "999",
                    ),
                ]
            }
        }
    ]

    result = replay_history.replay_history(
        "111122223333", org_client=org, athena_client=athena, output_location="s3://bucket/"
    )

    assert result["history"] == [
        {
            "role_arn": "arn:aws:iam::111122223333:role/Deployer",
            "event_source": "s3.amazonaws.com",
            "event_name": "PutBucketPolicy",
            "action": "s3:PutBucketPolicy",
            "call_count": 10,
        }
    ]
    assert result["total_calls_analyzed"] == 10
    assert result["sampled"] is False
