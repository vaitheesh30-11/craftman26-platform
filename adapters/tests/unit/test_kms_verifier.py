from __future__ import annotations

from unittest.mock import MagicMock

from iam_sentinel_adapters.evidence.kms_verifier import KmsVerifier


def test_verify_digest_returns_the_kms_signature_valid_flag() -> None:
    fake_kms = MagicMock()
    fake_kms.verify.return_value = {"SignatureValid": True}
    verifier = KmsVerifier(client=fake_kms)

    assert verifier.verify_digest(key_arn="arn:key", digest=b"digest", signature=b"sig") is True
    fake_kms.verify.assert_called_once_with(
        KeyId="arn:key",
        Message=b"digest",
        MessageType="DIGEST",
        Signature=b"sig",
        SigningAlgorithm="RSASSA_PSS_SHA_256",
    )


def test_verify_digest_false_on_mismatch() -> None:
    fake_kms = MagicMock()
    fake_kms.verify.return_value = {"SignatureValid": False}
    verifier = KmsVerifier(client=fake_kms)

    assert verifier.verify_digest(key_arn="arn:key", digest=b"digest", signature=b"bad") is False


def test_get_public_key_is_cached_across_calls() -> None:
    fake_kms = MagicMock()
    fake_kms.get_public_key.return_value = {"PublicKey": b"pubkey-bytes"}
    verifier = KmsVerifier(client=fake_kms)

    first = verifier.get_public_key("arn:key")
    second = verifier.get_public_key("arn:key")

    assert first == second == b"pubkey-bytes"
    fake_kms.get_public_key.assert_called_once()
