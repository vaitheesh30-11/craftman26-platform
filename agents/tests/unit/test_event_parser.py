"""event_parser handles both Bedrock action-group envelope shapes."""

from __future__ import annotations

import json

import pytest

from iam_sentinel_agents.errors import ContractError
from iam_sentinel_agents.tools.common.event_parser import (
    build_action_group_response,
    build_fallback_error_response,
    parse_action_group,
)

pytestmark = pytest.mark.unit

OPENAPI_EVENT = {
    "messageVersion": "1.0",
    "agent": {"name": "PassRoleCartographer", "id": "AGENT123", "alias": "dev", "version": "1"},
    "sessionId": "session-abc",
    "sessionAttributes": {"correlation_id": "01JBP2VHF9K3Q0Z8R7X6M5N4A3"},
    "actionGroup": "F1PassRoleActions",
    "apiPath": "/scan",
    "httpMethod": "POST",
    "requestBody": {
        "content": {
            "application/json": {
                "properties": [
                    {"name": "account_id", "type": "string", "value": "111122223333"},
                    {"name": "depth", "type": "integer", "value": "2"},
                    {"name": "dry_run", "type": "boolean", "value": "true"},
                ]
            }
        }
    },
}

FUNCTION_EVENT = {
    "messageVersion": "1.0",
    "agent": {"name": "PassRoleCartographer", "id": "AGENT123", "alias": "dev", "version": "1"},
    "sessionId": "session-abc",
    "sessionAttributes": {"correlation_id": "01JBP2VHF9K3Q0Z8R7X6M5N4A3"},
    "actionGroup": "F1PassRoleActions",
    "function": "passrole_scan",
    "parameters": [
        {"name": "account_id", "type": "string", "value": "111122223333"},
    ],
}


def test_parses_openapi_style_envelope() -> None:
    invocation = parse_action_group(OPENAPI_EVENT)
    assert invocation.session_id == "session-abc"
    assert invocation.correlation_id == "01JBP2VHF9K3Q0Z8R7X6M5N4A3"
    assert invocation.api_path == "/scan"
    assert invocation.http_method == "POST"
    assert invocation.action_group == "F1PassRoleActions"
    assert invocation.parameters == {
        "account_id": "111122223333",
        "depth": 2,
        "dry_run": True,
    }


def test_parses_function_style_envelope() -> None:
    invocation = parse_action_group(FUNCTION_EVENT)
    assert invocation.api_path == "/passrole_scan"
    assert invocation.http_method == "POST"
    assert invocation.parameters == {"account_id": "111122223333"}


def test_missing_session_id_raises_contract_error() -> None:
    broken = {k: v for k, v in OPENAPI_EVENT.items() if k != "sessionId"}
    with pytest.raises(ContractError, match="sessionId"):
        parse_action_group(broken)


def test_missing_correlation_id_raises_contract_error() -> None:
    broken = {**OPENAPI_EVENT, "sessionAttributes": {}}
    with pytest.raises(ContractError, match="correlation_id"):
        parse_action_group(broken)


def test_missing_api_path_and_function_raises_contract_error() -> None:
    broken = {k: v for k, v in OPENAPI_EVENT.items() if k not in {"apiPath", "httpMethod"}}
    with pytest.raises(ContractError, match=r"apiPath.*function"):
        parse_action_group(broken)


def test_missing_property_value_raises_contract_error() -> None:
    broken = json.loads(json.dumps(OPENAPI_EVENT))
    del broken["requestBody"]["content"]["application/json"]["properties"][0]["value"]
    with pytest.raises(ContractError, match="value"):
        parse_action_group(broken)


def test_non_dict_event_raises_contract_error() -> None:
    with pytest.raises(ContractError, match="JSON object"):
        parse_action_group([])


def test_build_action_group_response_shape() -> None:
    invocation = parse_action_group(OPENAPI_EVENT)
    response = build_action_group_response(invocation, http_status=200, body={"ok": True})
    assert response["response"]["actionGroup"] == "F1PassRoleActions"
    assert response["response"]["apiPath"] == "/scan"
    assert response["response"]["httpMethod"] == "POST"
    assert response["response"]["httpStatusCode"] == 200
    body = json.loads(response["response"]["responseBody"]["application/json"]["body"])
    assert body == {"ok": True}


def test_build_fallback_error_response_uses_available_fields() -> None:
    response = build_fallback_error_response(
        {"actionGroup": "F1PassRoleActions", "function": "passrole_scan"},
        http_status=400,
        message="boom",
    )
    assert response["response"]["actionGroup"] == "F1PassRoleActions"
    assert response["response"]["apiPath"] == "/passrole_scan"
    assert response["response"]["httpStatusCode"] == 400
    body = json.loads(response["response"]["responseBody"]["application/json"]["body"])
    assert body == {"error": "boom"}


def test_build_fallback_error_response_handles_completely_empty_event() -> None:
    response = build_fallback_error_response({}, http_status=400, message="boom")
    assert response["response"]["actionGroup"] == "unknown"
    assert response["response"]["apiPath"] == "unknown"
    assert response["response"]["httpMethod"] == "POST"
