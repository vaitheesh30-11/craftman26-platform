"""EvidenceClient tests use hand-written S3/KMS fakes rather than moto:
moto's mocked KMS does not implement real RSASSA-PSS cryptography, so it
cannot exercise the tamper-detection path this client exists for. The fake
KMS below uses the digest itself as the "signature" -- sufficient to prove
our plumbing (canonicalize -> hash -> sign -> store -> re-hash -> verify)
is wired correctly, which is what these tests own; AWS owns whether its
own crypto is correct.
"""

from __future__ import annotations

import io
from typing import Any

import pytest

from iam_sentinel_adapters.errors import EvidenceVerificationError
from iam_sentinel_adapters.evidence.client import EvidenceClient
from iam_sentinel_adapters.evidence.kms_signer import KmsSigner
from iam_sentinel_adapters.evidence.kms_verifier import KmsVerifier


class _FakeKms:
    def sign(self, *, KeyId: str, Message: bytes, MessageType: str, SigningAlgorithm: str) -> dict[str, Any]:
        return {"Signature": Message}

    def verify(
        self, *, KeyId: str, Message: bytes, MessageType: str, Signature: bytes, SigningAlgorithm: str
    ) -> dict[str, Any]:
        return {"SignatureValid": Signature == Message}


class _FakeS3:
    def __init__(self) -> None:
        self._objects: dict[tuple[str, str, str], bytes] = {}
        self._counter = 0

    def put_object(
        self, *, Bucket: str, Key: str, Body: bytes, ContentType: str, Metadata: dict[str, str]
    ) -> dict[str, Any]:
        self._counter += 1
        version_id = f"v{self._counter}"
        self._objects[(Bucket, Key, version_id)] = Body
        self._objects[(Bucket, Key, "")] = Body
        return {"VersionId": version_id}

    def get_object(self, *, Bucket: str, Key: str, VersionId: str = "") -> dict[str, Any]:
        body = self._objects[(Bucket, Key, VersionId)]
        return {"Body": io.BytesIO(body)}

    def corrupt(self, bucket: str, key: str, version_id: str) -> None:
        original = self._objects[(bucket, key, version_id)]
        mutated = original.replace(b"prod", b"dev0")
        self._objects[(bucket, key, version_id)] = mutated
        self._objects[(bucket, key, "")] = mutated


@pytest.fixture
def evidence_client() -> tuple[EvidenceClient, _FakeS3]:
    fake_s3 = _FakeS3()
    fake_kms = _FakeKms()
    client = EvidenceClient(
        bucket="sentinel-evidence-test",
        kms_key_arn="arn:aws:kms:us-east-1:111111111111:key/evidence",
        s3_client=fake_s3,  # type: ignore[arg-type]
        signer=KmsSigner(key_arn="arn:aws:kms:us-east-1:111111111111:key/evidence", client=fake_kms),  # type: ignore[arg-type]
        verifier=KmsVerifier(client=fake_kms),  # type: ignore[arg-type]
    )
    return client, fake_s3


def test_put_then_verify_round_trips_the_body(evidence_client: tuple[EvidenceClient, _FakeS3]) -> None:
    client, _ = evidence_client
    body = {"account_id": "111122223333", "role_arn": "arn:aws:iam::111122223333:role/prod"}

    ref = client.put_signed_evidence(
        kind="specialist_output", body=body, correlation_id="corr-1", feature_id="F1"
    )
    verified = client.verify(ref)

    assert verified == body


def test_tampered_body_fails_verification(evidence_client: tuple[EvidenceClient, _FakeS3]) -> None:
    client, fake_s3 = evidence_client
    body = {"role_arn": "arn:aws:iam::111122223333:role/prod"}

    ref = client.put_signed_evidence(
        kind="specialist_output", body=body, correlation_id="corr-2", feature_id="F1"
    )
    fake_s3.corrupt(ref.bucket, ref.key, ref.version_id)

    with pytest.raises(EvidenceVerificationError):
        client.verify(ref)


def test_key_is_content_addressed_by_feature_and_hash(
    evidence_client: tuple[EvidenceClient, _FakeS3]
) -> None:
    client, _ = evidence_client

    ref = client.put_signed_evidence(
        kind="fault", body={"error": "boom"}, correlation_id="corr-3", feature_id="F6"
    )

    assert ref.key.startswith("F6/")
    assert ref.key.endswith(f"{ref.sha256}.json")
