from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from iam_sentinel_adapters.errors import AccessDeniedError

from iam_sentinel_backend.auth.sigv4 import (
    from_apigw_identity,
    SigV4VerificationError,
    SigV4Verifier,
)


def test_from_apigw_identity_trusts_the_reflected_arn() -> None:
    principal = from_apigw_identity("arn:aws:iam::111122223333:user/alice")

    assert principal.arn == "arn:aws:iam::111122223333:user/alice"
    assert principal.auth_kind == "sigv4"


def test_from_apigw_identity_rejects_empty_arn() -> None:
    with pytest.raises(SigV4VerificationError):
        from_apigw_identity("")


def test_verify_signed_headers_resolves_and_caches() -> None:
    sts_client = MagicMock()
    sts_client.verify_signed_request.return_value = {
        "arn": "arn:aws:iam::111122223333:role/machine",
        "account": "111122223333",
        "user_id": "AROA",
    }
    verifier = SigV4Verifier(sts_client=sts_client)
    headers = {"Authorization": "AWS4-HMAC-SHA256 Credential=..."}

    first = verifier.verify_signed_headers(headers)
    second = verifier.verify_signed_headers(headers)

    assert first.arn == "arn:aws:iam::111122223333:role/machine"
    assert second == first
    sts_client.verify_signed_request.assert_called_once()


def test_verify_signed_headers_wraps_adapter_error() -> None:
    sts_client = MagicMock()
    sts_client.verify_signed_request.side_effect = AccessDeniedError("forged signature")
    verifier = SigV4Verifier(sts_client=sts_client)

    with pytest.raises(SigV4VerificationError):
        verifier.verify_signed_headers({"Authorization": "AWS4-HMAC-SHA256 forged"})
