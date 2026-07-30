from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from iam_sentinel_backend.auth.principal import Principal
from iam_sentinel_backend.errors import SentinelHTTPException
from iam_sentinel_backend.services.approval_service import ApprovalService

_PRINCIPAL = Principal(arn="arn:aws:iam::111122223333:role/Alice", auth_kind="cognito")


def _decision(status: str = "ESCALATED") -> dict[str, object]:
    return {
        "principal": _PRINCIPAL.arn,
        "decided_at": "2026-07-30T00:00:00+00:00",
        "decision_id": "01DECISIONID000000000000A",
        "status": status,
    }


def test_approve_transitions_to_auto_remediated() -> None:
    client = MagicMock()
    client.get_by_id.return_value = _decision()
    service = ApprovalService(client)

    result = service.approve(
        principal=_PRINCIPAL, decision_id="01DECISIONID000000000000A", reason="ok"
    )

    assert result.status == "AUTO_REMEDIATED"
    client.put.assert_called_once()


def test_reject_transitions_to_rejected() -> None:
    client = MagicMock()
    client.get_by_id.return_value = _decision()
    service = ApprovalService(client)

    result = service.reject(
        principal=_PRINCIPAL, decision_id="01DECISIONID000000000000A", reason="no"
    )

    assert result.status == "REJECTED"


def test_approve_404_when_decision_missing() -> None:
    client = MagicMock()
    client.get_by_id.return_value = None
    service = ApprovalService(client)

    with pytest.raises(SentinelHTTPException) as exc_info:
        service.approve(principal=_PRINCIPAL, decision_id="nonexistent", reason="")

    assert exc_info.value.status_code == 404


def test_approve_conflicts_on_an_already_resolved_decision() -> None:
    client = MagicMock()
    client.get_by_id.return_value = _decision(status="REJECTED")
    service = ApprovalService(client)

    with pytest.raises(SentinelHTTPException) as exc_info:
        service.approve(principal=_PRINCIPAL, decision_id="01DECISIONID000000000000A", reason="")

    assert exc_info.value.status_code == 409
