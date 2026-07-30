"""`passrole_scan` as a Bedrock action-group Lambda (envelope in, envelope
out) -- the scan logic itself is covered end-to-end via
test_pipeline_fixtures.py; this file only proves the `sentinel_handler`
wiring (§4 Step 1 -> §6 OpenAPI response shape).
"""

from __future__ import annotations

import json
from typing import Any, TYPE_CHECKING
from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws

from iam_sentinel_agents.tools.common import cross_account, runtime
from iam_sentinel_agents.tools.f1 import scan
from tests.unit.f1._provision import load_fixture, provision

if TYPE_CHECKING:
    from aws_lambda_powertools.utilities.typing import LambdaContext

pytestmark = pytest.mark.unit

ACCOUNT_ID = "123456789012"


class _FakeContext:
    aws_request_id = "req-f1-scan"

    def get_remaining_time_in_millis(self) -> int:
        return 30000


def _fake_context() -> LambdaContext:
    return _FakeContext()  # type: ignore[return-value]


def _event(account_id: str, principal_arn: str | None = None) -> dict[str, Any]:
    properties = [{"name": "account_id", "type": "string", "value": account_id}]
    if principal_arn is not None:
        properties.append({"name": "principal_arn", "type": "string", "value": principal_arn})
    return {
        "messageVersion": "1.0",
        "sessionId": "session-f1",
        "sessionAttributes": {"correlation_id": "01JBP2VHF9K3Q0Z8R7X6M5N4A3"},
        "actionGroup": "F1PassRoleActions",
        "apiPath": "/scan",
        "httpMethod": "POST",
        "requestBody": {"content": {"application/json": {"properties": properties}}},
    }


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    runtime.reset_cold_start_tracking_for_tests()
    cross_account.clear_cache_for_tests()
    yield
    cross_account.clear_cache_for_tests()


@mock_aws
def test_passrole_scan_returns_edges_in_the_openapi_response_shape() -> None:
    iam = boto3.client("iam", region_name="us-east-1")
    provision(iam, load_fixture("admin_shortcut"))

    with patch.object(cross_account, "assume", return_value=boto3.Session(region_name="us-east-1")):
        response = scan.passrole_scan(_event(ACCOUNT_ID), _fake_context())

    assert response["response"]["httpStatusCode"] == 200
    body = json.loads(response["response"]["responseBody"]["application/json"]["body"])
    # 2 principals (Deployer, AdminRole) and 2 edges: AdminRole's own
    # attached AdministratorAccess policy also grants it iam:PassRole via
    # Action=*/Resource=*, so it's a from_principal too, not just a target.
    assert body["principals_scanned"] == 2
    deployer_arn = f"arn:aws:iam::{ACCOUNT_ID}:user/Deployer"
    deployer_edges = [e for e in body["edges"] if e["from_principal"] == deployer_arn]
    assert len(deployer_edges) == 1
    assert deployer_edges[0]["resolved_role_arns"] == [f"arn:aws:iam::{ACCOUNT_ID}:role/AdminRole"]


@mock_aws
def test_passrole_scan_scoped_to_one_principal_with_no_grants_returns_empty() -> None:
    iam = boto3.client("iam", region_name="us-east-1")
    provision(iam, load_fixture("admin_shortcut"))
    iam.create_user(UserName="Bystander")

    with patch.object(cross_account, "assume", return_value=boto3.Session(region_name="us-east-1")):
        response = scan.passrole_scan(
            _event(ACCOUNT_ID, principal_arn=f"arn:aws:iam::{ACCOUNT_ID}:user/Bystander"),
            _fake_context(),
        )

    body = json.loads(response["response"]["responseBody"]["application/json"]["body"])
    assert body["edges"] == []
    assert body["principals_scanned"] == 1


def test_passrole_scan_missing_account_id_maps_to_500() -> None:
    event = {
        "messageVersion": "1.0",
        "sessionId": "session-f1",
        "sessionAttributes": {"correlation_id": "01JBP2VHF9K3Q0Z8R7X6M5N4A3"},
        "actionGroup": "F1PassRoleActions",
        "apiPath": "/scan",
        "httpMethod": "POST",
        "requestBody": {"content": {"application/json": {"properties": []}}},
    }
    response = scan.passrole_scan(event, _fake_context())
    assert response["response"]["httpStatusCode"] == 500
