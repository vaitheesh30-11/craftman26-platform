"""sentinel_handler decorator — parsing, hashing, HTTP mapping, metrics, logs."""

from __future__ import annotations

import json
import logging
from typing import Any, TYPE_CHECKING

import pytest

from iam_sentinel_agents.tools.common import runtime
from iam_sentinel_agents.tools.common.event_parser import ParsedInvocation

if TYPE_CHECKING:
    from aws_lambda_powertools.utilities.typing import LambdaContext

pytestmark = pytest.mark.unit

OPENAPI_EVENT: dict[str, Any] = {
    "messageVersion": "1.0",
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
                ]
            }
        }
    },
}


class _FakeContext:
    aws_request_id = "req-123"
    function_name = "passrole_scan"
    memory_limit_in_mb = 1024
    invoked_function_arn = "arn:aws:lambda:us-east-1:111122223333:function:passrole_scan"
    log_group_name = "/aws/lambda/passrole_scan"
    log_stream_name = "stream"

    def get_remaining_time_in_millis(self) -> int:
        return 30000


def _fake_context() -> LambdaContext:
    return _FakeContext()  # type: ignore[return-value]


@pytest.fixture(autouse=True)
def _reset_cold_start_tracking() -> None:
    runtime.reset_cold_start_tracking_for_tests()


def _read_json_lines(capsys: pytest.CaptureFixture[str]) -> list[dict[str, Any]]:
    captured = capsys.readouterr()
    out = captured.out + captured.err  # Powertools Logger writes to stderr
    records: list[dict[str, Any]] = []
    for raw_line in out.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            records.append(parsed)
    return records


def _metric_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in records if "_aws" in r]


def _log_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in records if "message" in r and "_aws" not in r]


def _broken_event() -> dict[str, Any]:
    return {k: v for k, v in OPENAPI_EVENT.items() if k != "sessionId"}


def test_successful_invocation_returns_200_envelope() -> None:
    @runtime.sentinel_handler(feature_id="F1", tool_name="passrole_scan")
    def handler(invocation: ParsedInvocation, context: LambdaContext) -> dict[str, Any]:
        assert invocation.parameters == {"account_id": "111122223333"}
        return {"edges": [], "principals_scanned": 0}

    response = handler(OPENAPI_EVENT, _fake_context())

    assert response["response"]["httpStatusCode"] == 200
    body = json.loads(response["response"]["responseBody"]["application/json"]["body"])
    assert body == {"edges": [], "principals_scanned": 0}


def test_handler_never_receives_raw_event() -> None:
    received: list[Any] = []

    @runtime.sentinel_handler(feature_id="F1")
    def handler(invocation: ParsedInvocation, context: LambdaContext) -> dict[str, Any]:
        received.append(invocation)
        return {}

    handler(OPENAPI_EVENT, _fake_context())

    assert len(received) == 1
    assert isinstance(received[0], ParsedInvocation)


def test_contract_error_maps_to_400() -> None:
    @runtime.sentinel_handler(feature_id="F1")
    def handler(invocation: ParsedInvocation, context: LambdaContext) -> dict[str, Any]:
        raise AssertionError("must not be called on a malformed envelope")

    response = handler(_broken_event(), _fake_context())

    assert response["response"]["httpStatusCode"] == 400


def test_unexpected_exception_maps_to_500() -> None:
    @runtime.sentinel_handler(feature_id="F1")
    def handler(invocation: ParsedInvocation, context: LambdaContext) -> dict[str, Any]:
        raise RuntimeError("boom")

    response = handler(OPENAPI_EVENT, _fake_context())

    assert response["response"]["httpStatusCode"] == 500
    body = json.loads(response["response"]["responseBody"]["application/json"]["body"])
    assert body == {"error": "boom"}


def test_emits_sentinel_invocation_metric_on_success(capsys: pytest.CaptureFixture[str]) -> None:
    @runtime.sentinel_handler(feature_id="F1")
    def handler(invocation: ParsedInvocation, context: LambdaContext) -> dict[str, Any]:
        return {}

    handler(OPENAPI_EVENT, _fake_context())

    metrics = _metric_records(_read_json_lines(capsys))
    assert len(metrics) == 1
    names = {m["Name"] for m in metrics[0]["_aws"]["CloudWatchMetrics"][0]["Metrics"]}
    assert "SentinelInvocation" in names
    assert metrics[0].get("outcome") == "success"
    assert metrics[0].get("feature_id") == "F1"


def test_emits_error_outcome_metric_on_exception(capsys: pytest.CaptureFixture[str]) -> None:
    @runtime.sentinel_handler(feature_id="F1")
    def handler(invocation: ParsedInvocation, context: LambdaContext) -> dict[str, Any]:
        raise RuntimeError("boom")

    handler(OPENAPI_EVENT, _fake_context())

    metrics = _metric_records(_read_json_lines(capsys))
    assert metrics[0].get("outcome") == "error"


def test_emits_rejected_outcome_metric_on_contract_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    @runtime.sentinel_handler(feature_id="F1")
    def handler(invocation: ParsedInvocation, context: LambdaContext) -> dict[str, Any]:
        raise AssertionError("must not be called")

    handler(_broken_event(), _fake_context())

    metrics = _metric_records(_read_json_lines(capsys))
    assert metrics[0].get("outcome") == "rejected"


def test_emits_cold_start_metric_only_on_first_invocation(
    capsys: pytest.CaptureFixture[str],
) -> None:
    @runtime.sentinel_handler(feature_id="F1", tool_name="passrole_scan")
    def handler(invocation: ParsedInvocation, context: LambdaContext) -> dict[str, Any]:
        return {}

    handler(OPENAPI_EVENT, _fake_context())
    first_names = {
        m["Name"]
        for record in _metric_records(_read_json_lines(capsys))
        for m in record["_aws"]["CloudWatchMetrics"][0]["Metrics"]
    }
    assert "ColdStart" in first_names

    handler(OPENAPI_EVENT, _fake_context())
    second_names = {
        m["Name"]
        for record in _metric_records(_read_json_lines(capsys))
        for m in record["_aws"]["CloudWatchMetrics"][0]["Metrics"]
    }
    assert "ColdStart" not in second_names


class _ListHandler(logging.Handler):
    """Attached directly to the Powertools logger instance.

    Powertools sets `propagate=False` on its logger (to avoid duplicate
    output), which breaks pytest's `caplog`; its singleton-per-service-name
    logger also rebinds `capsys`'s stream incorrectly across tests. Attaching
    our own handler straight to the logger object sidesteps both.
    """

    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))


def _completed_records(handler: _ListHandler) -> list[dict[str, Any]]:
    records = []
    for line in handler.lines:
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if parsed.get("message") == "tool_completed":
            records.append(parsed)
    return records


def test_logs_tool_completed_with_hashes() -> None:
    @runtime.sentinel_handler(feature_id="F1", tool_name="passrole_scan")
    def handler(invocation: ParsedInvocation, context: LambdaContext) -> dict[str, Any]:
        return {"edges": []}

    target_logger = logging.getLogger("iam-sentinel-f1")
    list_handler = _ListHandler()
    list_handler.setFormatter(target_logger.handlers[0].formatter)
    target_logger.addHandler(list_handler)
    try:
        handler(OPENAPI_EVENT, _fake_context())
    finally:
        target_logger.removeHandler(list_handler)

    completed = _completed_records(list_handler)
    assert len(completed) == 1
    record = completed[0]
    assert record["tool_name"] == "passrole_scan"
    assert record["input_hash"].startswith("sha256:")
    assert record["output_hash"].startswith("sha256:")
    assert record["correlation_id"] == "01JBP2VHF9K3Q0Z8R7X6M5N4A3"
    assert record["feature_id"] == "F1"
    assert isinstance(record["duration_ms"], int)
    assert record["aws_request_id"] == "req-123"


def test_correlation_id_does_not_leak_across_invocations() -> None:
    @runtime.sentinel_handler(feature_id="F1", tool_name="passrole_scan")
    def handler(invocation: ParsedInvocation, context: LambdaContext) -> dict[str, Any]:
        return {}

    second_event = json.loads(json.dumps(OPENAPI_EVENT))
    second_event["sessionAttributes"]["correlation_id"] = "01JBP2VHF9K3Q0Z8R7X6M5N4A4"

    target_logger = logging.getLogger("iam-sentinel-f1")
    list_handler = _ListHandler()
    list_handler.setFormatter(target_logger.handlers[0].formatter)
    target_logger.addHandler(list_handler)
    try:
        handler(OPENAPI_EVENT, _fake_context())
        list_handler.lines.clear()  # discard first invocation's records
        handler(second_event, _fake_context())
    finally:
        target_logger.removeHandler(list_handler)

    completed = _completed_records(list_handler)
    assert len(completed) == 1
    assert completed[0]["correlation_id"] == "01JBP2VHF9K3Q0Z8R7X6M5N4A4"


def test_build_tool_invocation_helper() -> None:
    invocation = runtime.build_tool_invocation(
        tool_name="passrole_scan",
        input_hash="1" * 64,
        output_hash="2" * 64,
        duration_ms=500,
        zelkova_check=None,
    )
    assert invocation.tool_name == "passrole_scan"
    assert invocation.duration_ms == 500
    assert invocation.zelkova_check is None
