"""`slr_scan` as a Bedrock action-group Lambda (envelope in, envelope out).
The scan logic itself is covered end-to-end via test_scan.py; this file
proves the `sentinel_handler` + `SlrsClient` wiring (§4 Step 3 -> §6
OpenAPI response shape).
"""

from __future__ import annotations

import json
from typing import Any, TYPE_CHECKING

import boto3
import pytest
from iam_sentinel_adapters.ddb.slrs import SlrsClient
from iam_sentinel_adapters.settings import settings as adapter_settings
from moto import mock_aws

from iam_sentinel_agents.tools.common import runtime
from iam_sentinel_agents.tools.f8 import scan

if TYPE_CHECKING:
    from aws_lambda_powertools.utilities.typing import LambdaContext

pytestmark = pytest.mark.unit

_REGION = "us-east-1"


class _FakeContext:
    aws_request_id = "req-f8-scan"

    def get_remaining_time_in_millis(self) -> int:
        return 30000


def _fake_context() -> LambdaContext:
    return _FakeContext()  # type: ignore[return-value]


def _event(proposed_scp: dict[str, Any]) -> dict[str, Any]:
    properties = [{"name": "proposed_scp", "type": "object", "value": json.dumps(proposed_scp)}]
    return {
        "messageVersion": "1.0",
        "sessionId": "session-f8",
        "sessionAttributes": {"correlation_id": "01JBP2VHF9K3Q0Z8R7X6M5N4A3"},
        "actionGroup": "F8SlrGuardianActions",
        "apiPath": "/scan",
        "httpMethod": "POST",
        "requestBody": {"content": {"application/json": {"properties": properties}}},
    }


@pytest.fixture(autouse=True)
def _reset_cold_start() -> None:
    runtime.reset_cold_start_tracking_for_tests()


@mock_aws
def test_slr_scan_returns_a_conflict_in_the_openapi_response_shape() -> None:
    boto3.setup_default_session(region_name=_REGION)
    ddb = boto3.resource("dynamodb", region_name=_REGION)
    ddb.create_table(
        TableName=adapter_settings.slrs_table,
        KeySchema=[{"AttributeName": "service_principal", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "service_principal", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    # DynamoDbHelper's default BreakerAccessor reads the circuit-breaker
    # table on every call -- needs to exist under moto too, or every put/
    # get raises ResourceNotFoundException before the real assertion runs.
    ddb.create_table(
        TableName=adapter_settings.breakers_table,
        KeySchema=[{"AttributeName": "breaker_name", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "breaker_name", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    SlrsClient().put(
        {
            "service_principal": "autoscaling.amazonaws.com",
            "slr_name": "AWSServiceRoleForAutoScaling",
            "required_actions": ["ec2:TerminateInstances"],
            "optional_actions": [],
            "core_actions": ["ec2:TerminateInstances"],
            "db_version": "1",
        }
    )
    proposed_scp = {
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Deny", "Action": "ec2:TerminateInstances", "Resource": "*"}],
    }

    response = scan.slr_scan(_event(proposed_scp), _fake_context())

    assert response["response"]["httpStatusCode"] == 200
    body = json.loads(response["response"]["responseBody"]["application/json"]["body"])
    assert body["total_slrs_checked"] == 1
    assert len(body["conflicts"]) == 1
    assert body["conflicts"][0]["impact"] == "CRITICAL"
