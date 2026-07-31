"""Full `handler()` envelope path (phase-07 §4 Step 1-2) with injected
mocks -- the decode/parse/evaluate logic itself is covered pure-ly in
`test_ingest.py`; this file exercises the DDB/evidence wiring around it,
same injection pattern `PrimePostTurnProcessor` and F1's `session`
parameter already established.
"""

from __future__ import annotations

import base64
import gzip
import json
from unittest.mock import MagicMock

import pytest

from iam_sentinel_agents.tools.f6.ingest import handler

pytestmark = pytest.mark.unit


def _cloudwatch_logs_event(*log_events: dict[str, object]) -> dict[str, object]:
    payload = {
        "logEvents": [
            {"id": str(i), "message": json.dumps(evt)} for i, evt in enumerate(log_events)
        ]
    }
    compressed = gzip.compress(json.dumps(payload).encode("utf-8"))
    return {"awslogs": {"data": base64.b64encode(compressed).decode("ascii")}}


def _mock_policies_client(chain: list[dict[str, object]]) -> MagicMock:
    client = MagicMock()
    client.get_chain.return_value = chain
    return client


def test_handler_persists_a_finding_for_each_violation() -> None:
    deny_chain = [
        {
            "level": "root",
            "policies": [
                {
                    "arn": "arn:aws:organizations::o-1:policy/p-root-deny",
                    "name": "RootDeny",
                    "document": {
                        "Statement": [
                            {
                                "Sid": "DenyIt",
                                "Effect": "Deny",
                                "Action": "organizations:DeletePolicy",
                                "Resource": "*",
                            }
                        ]
                    },
                }
            ],
        }
    ]
    event = _cloudwatch_logs_event(
        {
            "eventID": "evt-1",
            "eventName": "DeletePolicy",
            "eventSource": "organizations.amazonaws.com",
            "eventTime": "2026-07-30T12:00:00Z",
            "userIdentity": {"type": "IAMUser", "arn": "arn:aws:iam::111122223333:user/RootOps"},
            "recipientAccountId": "111122223333",
        }
    )
    policies = _mock_policies_client(deny_chain)
    findings = MagicMock()
    evidence = MagicMock()

    result = handler(event, None, policies=policies, findings=findings, evidence=evidence)  # type: ignore[arg-type]

    assert result == {"events_ingested": 1, "violations_found": 1}
    findings.put.assert_called_once()
    evidence.put_signed_evidence.assert_called_once()


def test_handler_is_a_no_op_for_a_clean_read_only_batch() -> None:
    event = _cloudwatch_logs_event(
        {
            "eventID": "evt-2",
            "eventName": "ListPolicies",
            "eventSource": "organizations.amazonaws.com",
            "eventTime": "2026-07-30T12:00:00Z",
            "userIdentity": {"type": "IAMUser", "arn": "arn:aws:iam::111122223333:user/RootOps"},
        }
    )
    policies = _mock_policies_client([])
    findings = MagicMock()
    evidence = MagicMock()

    result = handler(event, None, policies=policies, findings=findings, evidence=evidence)  # type: ignore[arg-type]

    assert result == {"events_ingested": 1, "violations_found": 0}
    findings.put.assert_not_called()
    evidence.put_signed_evidence.assert_not_called()


def test_handler_tolerates_a_malformed_log_record() -> None:
    payload = {"logEvents": [{"id": "0", "message": "not json"}]}
    compressed = gzip.compress(json.dumps(payload).encode("utf-8"))
    event = {"awslogs": {"data": base64.b64encode(compressed).decode("ascii")}}
    policies = _mock_policies_client([])
    findings = MagicMock()
    evidence = MagicMock()

    result = handler(event, None, policies=policies, findings=findings, evidence=evidence)  # type: ignore[arg-type]

    assert result == {"events_ingested": 1, "violations_found": 0}
    findings.put.assert_not_called()


def test_handler_returns_zero_counts_for_an_event_with_no_awslogs_data() -> None:
    policies = _mock_policies_client([])
    findings = MagicMock()
    evidence = MagicMock()

    result = handler({}, None, policies=policies, findings=findings, evidence=evidence)  # type: ignore[arg-type]

    assert result == {"events_ingested": 0, "violations_found": 0}
