from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from iam_sentinel_backend.auth.principal import Principal
from iam_sentinel_backend.errors import SentinelHTTPException
from iam_sentinel_backend.services.findings_service import FindingsService

_OWNER = "arn:aws:iam::111122223333:role/Alice"
_OTHER = "arn:aws:iam::111122223333:role/Bob"


def _finding(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "finding_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
        "feature_id": "F1",
        "account_id": "111122223333",
        "principal_arn": _OWNER,
        "severity": "HIGH",
        "title": "Overly permissive PassRole",
        "detail": "detail text",
        "aws_doc_citation": {
            "gap_id": "F1",
            "quote": "quote",
            "source": "IAM User Guide",
            "url": "https://docs.aws.amazon.com/x",
            "retrieved_on": "2026-07-30",
        },
        "detected_at": "2026-07-30T00:00:00+00:00",
    }
    base.update(overrides)
    return base


def _principal(arn: str = _OWNER, *, groups: tuple[str, ...] = ()) -> Principal:
    return Principal(arn=arn, groups=groups, auth_kind="cognito")


def test_list_findings_scopes_non_auditors_to_their_own_principal_arn() -> None:
    client = MagicMock()
    client.list_page.return_value = ([_finding()], None)
    service = FindingsService(client)

    service.list_findings(principal=_principal())

    _, kwargs = client.list_page.call_args
    assert kwargs["principal_arn"] == _OWNER


def test_list_findings_rejects_a_non_auditor_filtering_by_another_principal() -> None:
    client = MagicMock()
    service = FindingsService(client)

    with pytest.raises(SentinelHTTPException) as exc_info:
        service.list_findings(principal=_principal(), principal_arn=_OTHER)

    assert exc_info.value.code == "ACCESS_DENIED"


def test_list_findings_lets_auditors_filter_by_any_principal() -> None:
    client = MagicMock()
    client.list_page.return_value = ([], None)
    service = FindingsService(client)

    service.list_findings(principal=_principal(groups=("SentinelAuditors",)), principal_arn=_OTHER)

    _, kwargs = client.list_page.call_args
    assert kwargs["principal_arn"] == _OTHER


def test_get_finding_raises_404_when_missing() -> None:
    client = MagicMock()
    client.get_by_id.return_value = None
    service = FindingsService(client)

    with pytest.raises(SentinelHTTPException) as exc_info:
        service.get_finding(principal=_principal(), finding_id="nonexistent")

    assert exc_info.value.status_code == 404


def test_get_finding_denies_cross_principal_reads() -> None:
    client = MagicMock()
    client.get_by_id.return_value = _finding(principal_arn=_OTHER)
    service = FindingsService(client)

    with pytest.raises(SentinelHTTPException) as exc_info:
        service.get_finding(principal=_principal(), finding_id="x")

    assert exc_info.value.code == "ACCESS_DENIED"


def test_get_finding_allows_the_owning_principal() -> None:
    client = MagicMock()
    client.get_by_id.return_value = _finding()
    service = FindingsService(client)

    result = service.get_finding(principal=_principal(), finding_id="x")

    assert result.finding_id == "01ARZ3NDEKTSV4RRFFQ69G5FAV"
