"""`load_recent_violations`, `shadow_guard_report` (the Bedrock action-group
Lambda envelope), and `publish_weekly_report` -- all with injected mocks,
same pattern `test_ingest_handler.py` uses.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from iam_sentinel_agents.contracts.shadow_guard import ShadowViolationPayload
from iam_sentinel_agents.tools.f6.report import (
    load_recent_violations,
    publish_weekly_report,
    shadow_guard_report,
)

pytestmark = pytest.mark.unit


def _finding_item(action: str, severity: str) -> dict[str, object]:
    return {
        "payload": {
            "action": action,
            "principal_arn": "arn:aws:iam::111122223333:user/RootOps",
            "principal_type": "IAMUser",
            "would_be_denied_by_scp_arn": "arn:aws:organizations::o-1:policy/p-root-deny",
            "denying_statement_id": "DenyIt",
            "would_be_denied_at_level": "root",
            "event_id": "evt-1",
            "event_time": "2026-07-27T00:00:00+00:00",
            "severity": severity,
        }
    }


def test_load_recent_violations_unwraps_finding_payloads() -> None:
    findings_client = MagicMock()
    findings_client.list_page.return_value = ([_finding_item("iam:deleterole", "HIGH")], None)

    violations, total = load_recent_violations(days_back=7, findings=findings_client)

    assert total == 1
    assert violations[0].action == "iam:deleterole"


def test_load_recent_violations_skips_findings_with_no_payload() -> None:
    findings_client = MagicMock()
    findings_client.list_page.return_value = (
        [{"payload": {}}, _finding_item("s3:deleteobject", "MEDIUM")],
        None,
    )

    violations, total = load_recent_violations(days_back=7, findings=findings_client)

    assert total == 2
    assert len(violations) == 1


def _bedrock_event(**parameters: object) -> dict[str, object]:
    properties = [{"name": k, "type": "string", "value": str(v)} for k, v in parameters.items()]
    return {
        "sessionId": "sess-1",
        "sessionAttributes": {"correlation_id": "01JBP2VHF9K3Q0Z8R7X6M5N4A3"},
        "actionGroup": "f6-shadow-guard",
        "apiPath": "/report",
        "httpMethod": "POST",
        "requestBody": {"content": {"application/json": {"properties": properties}}},
    }


def test_shadow_guard_report_handler_returns_payload_and_controls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    findings_client = MagicMock()
    findings_client.list_page.return_value = (
        [_finding_item("organizations:deletepolicy", "CRITICAL")],
        None,
    )
    monkeypatch.setattr(
        "iam_sentinel_agents.tools.f6.report.FindingsClient", lambda: findings_client
    )

    response = shadow_guard_report(
        _bedrock_event(days_back=7, severity_filter="MEDIUM"), MagicMock()
    )

    body = json.loads(response["response"]["responseBody"]["application/json"]["body"])
    assert body["payload"]["violation_count"] == 1
    assert len(body["compensating_controls"]) >= 1


def test_publish_weekly_report_writes_to_the_reports_bucket() -> None:
    s3_client = MagicMock()
    payload = ShadowViolationPayload(
        days_back=7, total_events_ingested=1, violation_count=0, violations=[], top_actions=[]
    )

    key = publish_weekly_report(payload, [], s3_client=s3_client)

    assert key.startswith("f6/")
    assert key.endswith("/report.json")
    s3_client.put_object.assert_called_once()
    call_kwargs = s3_client.put_object.call_args.kwargs
    assert call_kwargs["Key"] == key
