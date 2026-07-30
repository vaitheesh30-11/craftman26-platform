from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from iam_sentinel_backend.auth.principal import Principal
from iam_sentinel_backend.errors import SentinelHTTPException
from iam_sentinel_backend.services.decisions_service import DecisionsService

_OWNER = "arn:aws:iam::111122223333:role/Alice"
_OTHER = "arn:aws:iam::111122223333:role/Bob"


def _decision(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "decision_id": "01DECISIONID000000000000A",
        "correlation_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
        "principal": _OWNER,
        "status": "ANSWERED",
        "narrative": "All clear.",
        "decided_at": "2026-07-30T00:00:00+00:00",
    }
    base.update(overrides)
    return base


def _principal(arn: str = _OWNER, *, groups: tuple[str, ...] = ()) -> Principal:
    return Principal(arn=arn, groups=groups, auth_kind="cognito")


def test_list_decisions_defaults_to_the_callers_own_principal() -> None:
    client = MagicMock()
    client.list_page.return_value = ([], None)
    service = DecisionsService(client)

    service.list_decisions(principal=_principal())

    args, _ = client.list_page.call_args
    assert args[0] == _OWNER


def test_list_decisions_rejects_a_non_auditor_requesting_another_principal() -> None:
    client = MagicMock()
    service = DecisionsService(client)

    with pytest.raises(SentinelHTTPException) as exc_info:
        service.list_decisions(principal=_principal(), principal_filter=_OTHER)

    assert exc_info.value.code == "ACCESS_DENIED"


def test_get_decision_404_when_missing() -> None:
    client = MagicMock()
    client.get_by_id.return_value = None
    service = DecisionsService(client)

    with pytest.raises(SentinelHTTPException) as exc_info:
        service.get_decision(principal=_principal(), decision_id="nonexistent")

    assert exc_info.value.status_code == 404


def test_get_decision_returns_the_callers_own_decision() -> None:
    client = MagicMock()
    client.get_by_id.return_value = _decision()
    service = DecisionsService(client)

    result = service.get_decision(principal=_principal(), decision_id="01DECISIONID000000000000A")

    assert result.status == "ANSWERED"


def test_get_decision_lets_auditors_read_any_principal() -> None:
    client = MagicMock()
    client.get_by_id.return_value = _decision(principal=_OTHER)
    service = DecisionsService(client)

    result = service.get_decision(
        principal=_principal(groups=("SentinelAuditors",)), decision_id="01DECISIONID000000000000A"
    )

    assert result.principal == _OTHER
    client.get_by_id.assert_called_once_with("01DECISIONID000000000000A", principal=None)
