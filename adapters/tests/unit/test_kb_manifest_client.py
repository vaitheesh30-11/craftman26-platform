"""KbManifestClient tests use the same hand-written S3/KMS fakes as
test_evidence_client.py, for the same reason: moto's mocked KMS can't
exercise real RSASSA-PSS crypto, only our own plumbing.
"""

from __future__ import annotations

import io
import json
from typing import Any

import pytest

from iam_sentinel_adapters.errors import ManifestVerificationError
from iam_sentinel_adapters.evidence.kms_signer import KmsSigner
from iam_sentinel_adapters.evidence.kms_verifier import KmsVerifier
from iam_sentinel_adapters.knowledge_base.manifest_client import KbManifestClient

_KEY_ARN = "arn:aws:kms:us-east-1:111111111111:key/kb-manifest"


class _FakeKms:
    def sign(self, *, KeyId: str, Message: bytes, MessageType: str, SigningAlgorithm: str) -> dict[str, Any]:
        return {"Signature": Message}

    def verify(
        self, *, KeyId: str, Message: bytes, MessageType: str, Signature: bytes, SigningAlgorithm: str
    ) -> dict[str, Any]:
        return {"SignatureValid": Signature == Message}


class _FakeS3:
    def __init__(self) -> None:
        self._objects: dict[tuple[str, str], bytes] = {}

    def put_object(self, *, Bucket: str, Key: str, Body: bytes, ContentType: str) -> dict[str, Any]:
        self._objects[(Bucket, Key)] = Body
        return {}

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        return {"Body": io.BytesIO(self._objects[(Bucket, Key)])}


@pytest.fixture
def manifest_client() -> tuple[KbManifestClient, _FakeS3]:
    fake_s3 = _FakeS3()
    fake_kms = _FakeKms()
    client = KbManifestClient(
        bucket="sentinelkb-manifest-test",
        key="manifest.json",
        kms_key_arn=_KEY_ARN,
        s3_client=fake_s3,  # type: ignore[arg-type]
        signer=KmsSigner(key_arn=_KEY_ARN, client=fake_kms),  # type: ignore[arg-type]
        verifier=KmsVerifier(client=fake_kms),  # type: ignore[arg-type]
    )
    return client, fake_s3


def _digest_hex_and_bytes() -> tuple[str, bytes]:
    import hashlib

    digest = hashlib.sha256(b"the sorted quotes list").digest()
    return digest.hex(), digest


def test_put_then_get_verified_round_trips(manifest_client: tuple[KbManifestClient, _FakeS3]) -> None:
    client, _ = manifest_client
    digest_hex, digest = _digest_hex_and_bytes()
    signature = client.sign(digest)
    body = {
        "manifest_version": "1",
        "total_quotes": 0,
        "quotes": [],
        "manifest_sha256": digest_hex,
        "signature": signature,
        "kms_key_arn": _KEY_ARN,
    }

    client.put(body=body)
    verified = client.get_verified()

    assert verified == body


def test_get_verified_rejects_tampered_signature(
    manifest_client: tuple[KbManifestClient, _FakeS3]
) -> None:
    client, fake_s3 = manifest_client
    digest_hex, digest = _digest_hex_and_bytes()
    signature = client.sign(digest)
    body = {
        "manifest_version": "1",
        "total_quotes": 0,
        "quotes": [],
        "manifest_sha256": digest_hex,
        "signature": signature,
        "kms_key_arn": _KEY_ARN,
    }
    client.put(body=body)

    flipped_last_char = "0" if digest_hex[-1] != "0" else "1"
    tampered = dict(body, manifest_sha256=digest_hex[:-1] + flipped_last_char)
    fake_s3._objects[("sentinelkb-manifest-test", "manifest.json")] = json.dumps(tampered).encode()

    with pytest.raises(ManifestVerificationError, match="signature verification failed"):
        client.get_verified()


def test_get_verified_rejects_invalid_json(manifest_client: tuple[KbManifestClient, _FakeS3]) -> None:
    client, fake_s3 = manifest_client
    fake_s3._objects[("sentinelkb-manifest-test", "manifest.json")] = b"not json"

    with pytest.raises(ManifestVerificationError, match="not valid JSON"):
        client.get_verified()


def test_put_also_writes_versioned_copy(manifest_client: tuple[KbManifestClient, _FakeS3]) -> None:
    client, fake_s3 = manifest_client
    body = {"manifest_version": "1"}

    client.put(body=body, version_key="manifest/1-2026-07-30.json")

    assert ("sentinelkb-manifest-test", "manifest/1-2026-07-30.json") in fake_s3._objects
