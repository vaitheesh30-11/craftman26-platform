"""`org_context_scan`/`org_context_suppress` as Bedrock action-group Lambdas
(envelope in, envelope out) -- proves the `sentinel_handler` wiring (phase-03
§6 OpenAPI response shape), mirroring `tests/unit/f1/test_scan_handler.py`.
Core classification/suppression logic is covered end-to-end in
test_classify.py/test_suppress.py.
"""

from __future__ import annotations

import json
from typing import Any, TYPE_CHECKING
from unittest.mock import MagicMock, patch

import boto3
import pytest

from iam_sentinel_agents.tools.common import cross_account, runtime
from iam_sentinel_agents.tools.f2 import classify, suppress
from iam_sentinel_agents.tools.f2.org_tree import OrgContext

if TYPE_CHECKING:
    from aws_lambda_powertools.utilities.typing import LambdaContext

pytestmark = pytest.mark.unit

ANALYZER_ARN = "arn:aws:access-analyzer:us-east-1:111122223333:analyzer/org-analyzer"
ORG = OrgContext(
    org_id="o-a1b2c3d4e5",
    master_account_id="111122223333",
    feature_set="ALL",
    account_ids=["111122223333"],
    ou_paths=["o-a1b2c3d4e5/r-ab12/"],
)


class _FakeContext:
    aws_request_id = "req-f2"

    def get_remaining_time_in_millis(self) -> int:
        return 30000


def _fake_context() -> LambdaContext:
    return _FakeContext()  # type: ignore[return-value]


def _event(api_path: str, properties: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "messageVersion": "1.0",
        "sessionId": "session-f2",
        "sessionAttributes": {"correlation_id": "01JBP2VHF9K3Q0Z8R7X6M5N4A3"},
        "actionGroup": "F2OrgContextActions",
        "apiPath": api_path,
        "httpMethod": "POST",
        "requestBody": {"content": {"application/json": {"properties": properties}}},
    }


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    runtime.reset_cold_start_tracking_for_tests()
    cross_account.clear_cache_for_tests()
    yield
    cross_account.clear_cache_for_tests()


def test_org_context_scan_returns_payload_in_the_openapi_response_shape() -> None:
    fake_aa = MagicMock()
    fake_aa.get_paginator.return_value.paginate.return_value = [{"findings": [{"id": "f-1"}]}]
    fake_aa.get_finding.return_value = {
        "finding": {"id": "f-1", "condition": {"aws:PrincipalOrgId": ORG.org_id}}
    }

    event = _event("/scan", [{"name": "analyzer_arn", "type": "string", "value": ANALYZER_ARN}])

    with (
        patch.object(cross_account, "assume", return_value=boto3.Session(region_name="us-east-1")),
        patch.object(classify, "fetch_org_context", return_value=ORG),
        patch.object(classify, "_access_analyzer_client", return_value=fake_aa),
    ):
        response = classify.org_context_scan(event, _fake_context())

    assert response["response"]["httpStatusCode"] == 200
    body = json.loads(response["response"]["responseBody"]["application/json"]["body"])
    assert body["analyzer_arn"] == ANALYZER_ARN
    assert body["total_findings"] == 1
    assert body["classifications"][0]["classification"] == "FALSE_POSITIVE_ORG_SCOPED"


def test_org_context_scan_missing_analyzer_arn_maps_to_500() -> None:
    event = _event("/scan", [])
    response = classify.org_context_scan(event, _fake_context())
    assert response["response"]["httpStatusCode"] == 500


def test_org_context_suppress_returns_archived_count_in_the_openapi_response_shape() -> None:
    fake_client = MagicMock()
    fake_session = boto3.Session(region_name="us-east-1")
    fake_client.exceptions.ResourceNotFoundException = type(
        "ResourceNotFoundException", (Exception,), {}
    )
    fake_client.get_archive_rule.side_effect = fake_client.exceptions.ResourceNotFoundException()

    event = _event(
        "/suppress",
        [
            {"name": "analyzer_arn", "type": "string", "value": ANALYZER_ARN},
            {"name": "finding_ids", "type": "array", "value": json.dumps(["f-1", "f-2"])},
        ],
    )

    with (
        patch.object(cross_account, "assume", return_value=fake_session),
        patch.object(suppress, "fetch_org_context", return_value=ORG),
        patch.object(boto3.Session, "client", return_value=fake_client),
    ):
        response = suppress.org_context_suppress(event, _fake_context())

    assert response["response"]["httpStatusCode"] == 200
    body = json.loads(response["response"]["responseBody"]["application/json"]["body"])
    assert body["archived"] == 2
    assert body["rule_id"] == f"sentinel-org-scoped-suppression-{ORG.org_id}"


def test_org_context_suppress_missing_finding_ids_maps_to_500() -> None:
    event = _event("/suppress", [{"name": "analyzer_arn", "type": "string", "value": ANALYZER_ARN}])
    response = suppress.org_context_suppress(event, _fake_context())
    assert response["response"]["httpStatusCode"] == 500
