"""`memory_actions_handler` -- the shared `MemoryActions` Bedrock action-
group Lambda (phase-14 §4/§6): envelope parsing, principal-scoped recall,
writer-role-restricted remember, and fail-closed error mapping.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from moto import mock_aws

from iam_sentinel_agents.tools.memory import actions
from tests.unit.memory import _ddb

pytestmark = pytest.mark.unit

_PRINCIPAL = "arn:aws:iam::111122223333:user/alice"


def _openapi_event(
    *, api_path: str, properties: list[dict[str, Any]], principal: str = _PRINCIPAL
) -> dict[str, Any]:
    return {
        "messageVersion": "1.0",
        "sessionId": "session-1",
        "sessionAttributes": {"correlation_id": "01JBP2VHF9K3Q0Z8R7X6M5N4A1"},
        "promptSessionAttributes": {"principal": principal},
        "actionGroup": "MemoryActions",
        "apiPath": api_path,
        "httpMethod": "POST",
        "requestBody": {
            "content": {"application/json": {"properties": properties}}
        },
    }


def _response_body(response: dict[str, Any]) -> dict[str, Any]:
    raw = response["response"]["responseBody"]["application/json"]["body"]
    return json.loads(raw)


@mock_aws
def test_recall_episodic_returns_200_with_empty_hits_for_new_principal() -> None:
    with patch("iam_sentinel_agents.tools.memory.actions.MemoryClient", return_value=_ddb.memory_client()):
        event = _openapi_event(
            api_path="/recall",
            properties=[
                {"name": "kind", "type": "string", "value": "episodic"},
                {"name": "top_k", "type": "integer", "value": "5"},
            ],
        )
        response = actions.memory_actions_handler(event, MagicMock(aws_request_id="req-1"))

    assert response["response"]["httpStatusCode"] == 200
    body = _response_body(response)
    assert body["kind"] == "episodic"
    assert body["hits"] == []


@mock_aws
def test_recall_procedural_hit_after_remember() -> None:
    memory = _ddb.memory_client()
    memory.procedural_put("scp_effective_policy", "a" * 64, {"allowed": True}, ttl_seconds=900)
    with patch("iam_sentinel_agents.tools.memory.actions.MemoryClient", return_value=memory):
        event = _openapi_event(
            api_path="/recall",
            properties=[
                {"name": "kind", "type": "string", "value": "procedural"},
                {"name": "pattern_kind", "type": "string", "value": "scp_effective_policy"},
                {"name": "pattern_hash", "type": "string", "value": "a" * 64},
            ],
        )
        response = actions.memory_actions_handler(event, MagicMock(aws_request_id="req-2"))

    body = _response_body(response)
    assert body["total_scanned"] == 1


@mock_aws
def test_recall_unknown_kind_returns_400() -> None:
    with patch("iam_sentinel_agents.tools.memory.actions.MemoryClient", return_value=_ddb.memory_client()):
        event = _openapi_event(
            api_path="/recall",
            properties=[{"name": "kind", "type": "string", "value": "bogus"}],
        )
        response = actions.memory_actions_handler(event, MagicMock(aws_request_id="req-3"))

    assert response["response"]["httpStatusCode"] == 400


@mock_aws
def test_remember_without_correct_writer_role_returns_403() -> None:
    with patch("iam_sentinel_agents.tools.memory.actions.MemoryClient", return_value=_ddb.memory_client()):
        record = {
            "pattern_kind": "scp_effective_policy",
            "pattern_hash": "b" * 64,
            "result": {},
            "ttl": 900,
        }
        event = _openapi_event(
            api_path="/remember",
            properties=[
                {"name": "kind", "type": "string", "value": "procedural"},
                {"name": "record", "type": "object", "value": json.dumps(record)},
            ],
        )
        response = actions.memory_actions_handler(event, MagicMock(aws_request_id="req-4"))

    assert response["response"]["httpStatusCode"] == 403


@mock_aws
def test_remember_procedural_with_correct_writer_role_returns_200() -> None:
    with patch("iam_sentinel_agents.tools.memory.actions.MemoryClient", return_value=_ddb.memory_client()):
        record = {
            "pattern_kind": "scp_effective_policy",
            "pattern_hash": "c" * 64,
            "result": {"ok": True},
            "ttl": 900,
            "writer_role": "tool_memoizer",
        }
        event = _openapi_event(
            api_path="/remember",
            properties=[
                {"name": "kind", "type": "string", "value": "procedural"},
                {"name": "record", "type": "object", "value": json.dumps(record)},
            ],
        )
        # writer_role lives at the params level, not inside `record`, per
        # `_dispatch_remember` -- add it as its own property too.
        event["requestBody"]["content"]["application/json"]["properties"].append(
            {"name": "writer_role", "type": "string", "value": "tool_memoizer"}
        )
        response = actions.memory_actions_handler(event, MagicMock(aws_request_id="req-5"))

    assert response["response"]["httpStatusCode"] == 200
    assert _response_body(response) == {"written": True}


def test_malformed_envelope_returns_400_fallback() -> None:
    response = actions.memory_actions_handler({}, MagicMock(aws_request_id="req-6"))
    assert response["response"]["httpStatusCode"] == 400
