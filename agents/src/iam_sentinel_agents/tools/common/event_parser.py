"""Parse Bedrock action-group Lambda envelopes into a typed model.

Bedrock invokes action-group Lambdas in one of two envelope shapes:

1. OpenAPI-schema action groups (the shape every IAM Sentinel action group
   uses — see agents/src/iam_sentinel_agents/action_groups/*.yaml):
   `apiPath` + `httpMethod` + `requestBody.content."application/json".properties`.
2. Function-details action groups (a newer, schema-less Bedrock shape):
   `function` + `parameters: [{name, type, value}]`.

`parse_action_group` normalizes both into one `ParsedInvocation`. Callers
never branch on envelope shape.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import Field

from iam_sentinel_agents.contracts.common import Base
from iam_sentinel_agents.errors import ContractError

_JSON_CONTENT_TYPE = "application/json"


class ParsedInvocation(Base):
    session_id: str = Field(min_length=1, max_length=256)
    correlation_id: str = Field(min_length=1, max_length=256)
    api_path: str = Field(min_length=1, max_length=256)
    http_method: str = Field(min_length=1, max_length=16)
    parameters: dict[str, Any] = Field(default_factory=dict)
    action_group: str = Field(min_length=1, max_length=256)


def _require(mapping: dict[str, Any], key: str, *, envelope_kind: str) -> Any:
    if key not in mapping:
        raise ContractError(f"{envelope_kind} envelope missing required key {key!r}")
    return mapping[key]


def _coerce_typed_value(raw_type: str, raw_value: str) -> Any:
    """Bedrock always sends parameter values as strings with a declared type."""
    normalized = raw_type.strip().lower()
    if normalized == "integer":
        return int(raw_value)
    if normalized == "number":
        return float(raw_value)
    if normalized == "boolean":
        return raw_value.strip().lower() in {"true", "1", "yes"}
    if normalized in ("array", "object"):
        # Bedrock JSON-encodes both `array` and `object` typed parameters
        # into the same string `value` field every scalar type uses --
        # F1..F7's action groups only ever declare scalar parameters
        # (string/integer/boolean), so this branch was untested until F8's
        # `slr_scan(proposed_scp: object)` became the first caller to pass
        # a JSON object parameter. Real bug found while building phase-09;
        # fixed here rather than left for whichever specialist first needed
        # an object-typed tool parameter (docs/decisions/0023).
        return json.loads(raw_value)
    return raw_value


def _extract_openapi_parameters(request_body: dict[str, Any]) -> dict[str, Any]:
    content = request_body.get("content", {})
    json_content = content.get(_JSON_CONTENT_TYPE)
    if json_content is None:
        return {}
    properties = json_content.get("properties", [])
    parameters: dict[str, Any] = {}
    for prop in properties:
        name = _require(prop, "name", envelope_kind="OpenAPI property")
        value = _require(prop, "value", envelope_kind="OpenAPI property")
        prop_type = prop.get("type", "string")
        parameters[name] = _coerce_typed_value(prop_type, value)
    return parameters


def _extract_function_parameters(raw_parameters: list[dict[str, Any]]) -> dict[str, Any]:
    parameters: dict[str, Any] = {}
    for prop in raw_parameters:
        name = _require(prop, "name", envelope_kind="function parameter")
        value = _require(prop, "value", envelope_kind="function parameter")
        prop_type = prop.get("type", "string")
        parameters[name] = _coerce_typed_value(prop_type, value)
    return parameters


def parse_action_group(event: Any) -> ParsedInvocation:
    """Parse a Bedrock action-group Lambda event into a typed invocation.

    `event` is typed `Any` deliberately: this is the outermost parsing
    boundary and must defend against a caller passing something that isn't
    even a JSON object, not just a dict with missing keys.

    Raises ContractError on any missing required field or wrong root type —
    never returns a partially-populated model.
    """
    if not isinstance(event, dict):
        raise ContractError("event must be a JSON object")

    session_id = _require(event, "sessionId", envelope_kind="action-group")
    session_attributes = event.get("sessionAttributes", {}) or {}
    correlation_id = session_attributes.get("correlation_id")
    if not correlation_id:
        raise ContractError("sessionAttributes.correlation_id is required")

    action_group = _require(event, "actionGroup", envelope_kind="action-group")

    if "apiPath" in event:
        api_path = _require(event, "apiPath", envelope_kind="OpenAPI action-group")
        http_method = _require(event, "httpMethod", envelope_kind="OpenAPI action-group")
        request_body = event.get("requestBody", {}) or {}
        parameters = _extract_openapi_parameters(request_body)
    elif "function" in event:
        function_name = _require(event, "function", envelope_kind="function action-group")
        api_path = f"/{function_name}"
        http_method = "POST"
        raw_parameters = event.get("parameters", []) or []
        parameters = _extract_function_parameters(raw_parameters)
    else:
        raise ContractError(
            "action-group envelope must contain either 'apiPath' (OpenAPI style) "
            "or 'function' (function-details style)"
        )

    try:
        return ParsedInvocation(
            session_id=session_id,
            correlation_id=correlation_id,
            api_path=api_path,
            http_method=http_method,
            parameters=parameters,
            action_group=action_group,
        )
    except Exception as exc:
        raise ContractError(f"failed to build ParsedInvocation: {exc}") from exc


def build_action_group_response(
    invocation: ParsedInvocation,
    *,
    http_status: int,
    body: dict[str, Any],
) -> dict[str, Any]:
    """Compose the Bedrock action-group response envelope."""
    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": invocation.action_group,
            "apiPath": invocation.api_path,
            "httpMethod": invocation.http_method,
            "httpStatusCode": http_status,
            "responseBody": {
                _JSON_CONTENT_TYPE: {"body": json.dumps(body, separators=(",", ":"))}
            },
        },
    }


def build_fallback_error_response(
    event: dict[str, Any], *, http_status: int, message: str
) -> dict[str, Any]:
    """Best-effort error envelope for events too malformed to fully parse.

    Bedrock needs `actionGroup`/`apiPath`/`httpMethod` echoed back to route
    the response. `event` is declared `dict[str, Any]` because AWS Lambda's
    runtime contract guarantees the raw event is always a JSON object for
    every trigger IAM Sentinel uses — unlike `parse_action_group`, this
    helper is never called with a non-dict.
    """
    action_group = event.get("actionGroup", "unknown")
    raw_function = event.get("function")
    fallback_path = f"/{raw_function}" if raw_function else None
    api_path = event.get("apiPath") or fallback_path or "unknown"
    http_method = event.get("httpMethod", "POST")
    error_body = json.dumps({"error": message}, separators=(",", ":"))

    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": action_group,
            "apiPath": api_path,
            "httpMethod": http_method,
            "httpStatusCode": http_status,
            "responseBody": {_JSON_CONTENT_TYPE: {"body": error_body}},
        },
    }
