from __future__ import annotations

import base64
from unittest.mock import MagicMock

from iam_sentinel_adapters.evidence.kms_signer import KmsSigner


def test_sign_digest_returns_base64_of_the_raw_signature() -> None:
    fake_kms = MagicMock()
    fake_kms.sign.return_value = {"Signature": b"raw-signature-bytes"}
    signer = KmsSigner(key_arn="arn:aws:kms:us-east-1:111111111111:key/abc", client=fake_kms)

    result = signer.sign_digest(b"some-digest")

    assert result == base64.b64encode(b"raw-signature-bytes").decode("ascii")
    fake_kms.sign.assert_called_once_with(
        KeyId="arn:aws:kms:us-east-1:111111111111:key/abc",
        Message=b"some-digest",
        MessageType="DIGEST",
        SigningAlgorithm="RSASSA_PSS_SHA_256",
    )
