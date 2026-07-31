from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from iam_sentinel_adapters.errors import EvidenceVerificationError

from iam_sentinel_backend.auth.principal import AuthKind, Principal
from iam_sentinel_backend.errors import SentinelHTTPException
from iam_sentinel_backend.services.evidence_service import EvidenceService, parse_evidence_ref
from iam_sentinel_backend.settings import settings

_REF = "sentinel-evidence-dev/F1/2026/07/31/corr-1/specialist_output/deadbeef.json@v1"


def _principal(*, groups: tuple[str, ...] = (), auth_kind: AuthKind = "cognito") -> Principal:
    return Principal(arn="arn:aws:iam::111122223333:role/Alice", groups=groups, auth_kind=auth_kind)


def test_parse_evidence_ref_splits_bucket_key_and_version() -> None:
    bucket, key, version_id = parse_evidence_ref(_REF)

    assert bucket == "sentinel-evidence-dev"
    assert key == "F1/2026/07/31/corr-1/specialist_output/deadbeef.json"
    assert version_id == "v1"


def test_parse_evidence_ref_rejects_a_malformed_ref() -> None:
    with pytest.raises(SentinelHTTPException) as exc_info:
        parse_evidence_ref("not-a-valid-ref")

    assert exc_info.value.status_code == 400


def test_get_evidence_denies_non_privileged_groups() -> None:
    evidence_client = MagicMock()
    service = EvidenceService(evidence_client)

    with pytest.raises(SentinelHTTPException) as exc_info:
        service.get_evidence(principal=_principal(groups=()), ref=_REF)

    assert exc_info.value.status_code == 403
    evidence_client.verify_by_location.assert_not_called()


def test_get_evidence_returns_body_for_auditors() -> None:
    evidence_client = MagicMock()
    evidence_client.verify_by_location.return_value = {"kind": "specialist_output"}
    service = EvidenceService(evidence_client)
    auditor = _principal(groups=(settings.cognito_group_auditors,))

    body = service.get_evidence(principal=auditor, ref=_REF)

    assert body == {"kind": "specialist_output"}


def test_get_evidence_propagates_tamper_detection_for_502() -> None:
    evidence_client = MagicMock()
    evidence_client.verify_by_location.side_effect = EvidenceVerificationError("tampered")
    service = EvidenceService(evidence_client)
    auditor = _principal(groups=(settings.cognito_group_operators,))

    with pytest.raises(EvidenceVerificationError):
        service.get_evidence(principal=auditor, ref=_REF)


def test_get_evidence_returns_404_when_object_missing() -> None:
    evidence_client = MagicMock()
    evidence_client.verify_by_location.return_value = None
    service = EvidenceService(evidence_client)
    auditor = _principal(groups=(settings.cognito_group_auditors,))

    with pytest.raises(SentinelHTTPException) as exc_info:
        service.get_evidence(principal=auditor, ref=_REF)

    assert exc_info.value.status_code == 404
