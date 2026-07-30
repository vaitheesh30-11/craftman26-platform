"""`passrole_graph` as a Bedrock action-group Lambda (envelope in, envelope
out) -- graph logic itself is covered end-to-end via
test_pipeline_fixtures.py; this file only proves the `sentinel_handler`
wiring (§4 Step 2 -> §6 OpenAPI response shape) and the depth cap.
"""

from __future__ import annotations

import json
from typing import Any, TYPE_CHECKING
from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws

from iam_sentinel_agents.tools.common import cross_account, runtime
from iam_sentinel_agents.tools.f1 import graph
from tests.unit.f1._provision import load_fixture, provision

if TYPE_CHECKING:
    from aws_lambda_powertools.utilities.typing import LambdaContext

pytestmark = pytest.mark.unit

ACCOUNT_ID = "123456789012"


class _FakeContext:
    aws_request_id = "req-f1-graph"

    def get_remaining_time_in_millis(self) -> int:
        return 30000


def _fake_context() -> LambdaContext:
    return _FakeContext()  # type: ignore[return-value]


def _event(edges: list[dict[str, Any]], depth: int | None = None) -> dict[str, Any]:
    properties = [{"name": "edges", "type": "array", "value": json.dumps(edges)}]
    if depth is not None:
        properties.append({"name": "depth", "type": "integer", "value": str(depth)})
    return {
        "messageVersion": "1.0",
        "sessionId": "session-f1",
        "sessionAttributes": {"correlation_id": "01JBP2VHF9K3Q0Z8R7X6M5N4A3"},
        "actionGroup": "F1PassRoleActions",
        "apiPath": "/graph",
        "httpMethod": "POST",
        "requestBody": {"content": {"application/json": {"properties": properties}}},
    }


def _admin_shortcut_edge() -> dict[str, Any]:
    return {
        "from_principal": f"arn:aws:iam::{ACCOUNT_ID}:user/Deployer",
        "passable_role_pattern": f"arn:aws:iam::{ACCOUNT_ID}:role/AdminRole",
        "resolved_role_arns": [f"arn:aws:iam::{ACCOUNT_ID}:role/AdminRole"],
        "condition_summary": {},
        "grant_source_policy_arn": "arn:aws:iam::inline:user/Deployer/PassRoleAdmin",
        "grant_statement_id": "AllowPassAdminRole",
    }


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    runtime.reset_cold_start_tracking_for_tests()
    cross_account.clear_cache_for_tests()
    yield
    cross_account.clear_cache_for_tests()


@mock_aws
def test_passrole_graph_classifies_admin_shortcut_as_critical() -> None:
    iam = boto3.client("iam", region_name="us-east-1")
    provision(iam, load_fixture("admin_shortcut"))

    with patch.object(cross_account, "assume", return_value=boto3.Session(region_name="us-east-1")):
        response = graph.passrole_graph(_event([_admin_shortcut_edge()]), _fake_context())

    assert response["response"]["httpStatusCode"] == 200
    body = json.loads(response["response"]["responseBody"]["application/json"]["body"])
    principal_arn = f"arn:aws:iam::{ACCOUNT_ID}:user/Deployer"
    assert principal_arn in body["critical_principals"]
    assert body["paths_by_principal"][principal_arn][0]["reached_privilege"] == "AdministratorAccess"
    assert body["paths_by_principal"][principal_arn][0]["hop_count"] == 1


def test_passrole_graph_with_no_edges_returns_empty_shape() -> None:
    response = graph.passrole_graph(_event([]), _fake_context())
    body = json.loads(response["response"]["responseBody"]["application/json"]["body"])
    assert body == {"paths_by_principal": {}, "critical_principals": []}


def test_build_blast_paths_caps_depth_at_two_even_if_a_larger_value_is_requested() -> None:
    result = graph.build_blast_paths([], depth=5)
    assert result["graph_stats"]["depth"] == 2
