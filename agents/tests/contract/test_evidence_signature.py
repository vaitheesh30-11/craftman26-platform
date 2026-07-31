"""phase-13 §3 Step 3 — evidence signature contract test: KMS-signed
evidence is verifiable by the public key, and canonicalization is stable
regardless of the producer's own key insertion order. Uses the same
digest-as-signature fake KMS `adapters/tests/unit/test_evidence_client.py`
establishes (moto's mocked KMS lacks real RSASSA-PSS crypto) against the
exact evidence-body shape `PrimePostTurnProcessor.process` composes
(agents/src/iam_sentinel_agents/prime/post_turn.py) -- a genuine
agents-side contract test, not a restatement of the adapters-side one.
"""

from __future__ import annotations

import io
from typing import Any

import pytest
from botocore.exceptions import ClientError
from iam_sentinel_adapters.errors import EvidenceVerificationError
from iam_sentinel_adapters.evidence.client import EvidenceClient
from iam_sentinel_adapters.evidence.kms_signer import KmsSigner
from iam_sentinel_adapters.evidence.kms_verifier import KmsVerifier

_KEY_ARN = "arn:aws:kms:us-east-1:111122223333:key/e2e-fake-key"


class _FakeKms:
    def sign(
        self, *, KeyId: str, Message: bytes, MessageType: str, SigningAlgorithm: str
    ) -> dict[str, Any]:
        return {"Signature": Message}

    def verify(
        self,
        *,
        KeyId: str,
        Message: bytes,
        MessageType: str,
        Signature: bytes,
        SigningAlgorithm: str,
    ) -> dict[str, Any]:
        return {"SignatureValid": Signature == Message}


class _FakeS3:
    def __init__(self) -> None:
        self._objects: dict[tuple[str, str, str], bytes] = {}
        self._metadata: dict[tuple[str, str, str], dict[str, str]] = {}
        self._counter = 0

    def put_object(
        self, *, Bucket: str, Key: str, Body: bytes, ContentType: str, Metadata: dict[str, str]
    ) -> dict[str, Any]:
        self._counter += 1
        version_id = f"v{self._counter}"
        for key in ((Bucket, Key, version_id), (Bucket, Key, "")):
            self._objects[key] = Body
            self._metadata[key] = Metadata
        return {"VersionId": version_id}

    def get_object(self, *, Bucket: str, Key: str, VersionId: str = "") -> dict[str, Any]:
        return {"Body": io.BytesIO(self._objects[(Bucket, Key, VersionId)])}

    def head_object(self, *, Bucket: str, Key: str, VersionId: str = "") -> dict[str, Any]:
        key = (Bucket, Key, VersionId)
        if key not in self._objects:
            raise ClientError({"Error": {"Code": "404", "Message": "not found"}}, "HeadObject")
        return {"Metadata": self._metadata[key]}


def _evidence_client() -> tuple[EvidenceClient, _FakeS3]:
    fake_s3 = _FakeS3()
    fake_kms = _FakeKms()
    client = EvidenceClient(
        bucket="sentinel-evidence-contract-test",
        kms_key_arn=_KEY_ARN,
        s3_client=fake_s3,  # type: ignore[arg-type]
        signer=KmsSigner(key_arn=_KEY_ARN, client=fake_kms),  # type: ignore[arg-type]
        verifier=KmsVerifier(client=fake_kms),  # type: ignore[arg-type]
    )
    return client, fake_s3


def _decision_evidence_body(*, decision_id: str, correlation_id: str) -> dict[str, Any]:
    """Same shape `PrimePostTurnProcessor.process` builds -- decision_id,
    correlation_id, principal, status, narrative, specialist_verdicts.
    """
    return {
        "decision_id": decision_id,
        "correlation_id": correlation_id,
        "principal": "arn:aws:iam::111122223333:role/Auditor",
        "status": "ANSWERED",
        "narrative": "1 CRITICAL PassRole finding.",
        "specialist_verdicts": [{"feature_id": "F1", "verdict": "CONFIRM"}],
    }


def test_decision_evidence_round_trips_and_verifies_by_public_key() -> None:
    client, _ = _evidence_client()
    body = _decision_evidence_body(decision_id="d-1", correlation_id="c-1")

    ref = client.put_signed_evidence(
        kind="specialist_output", body=body, correlation_id="c-1", feature_id="F1"
    )
    verified = client.verify(ref)

    assert verified == body


def test_canonicalization_is_stable_regardless_of_key_insertion_order() -> None:
    """Two dicts with identical content but different key insertion order
    must produce byte-identical canonical output -- and therefore the same
    sha256 and signature -- proving `canonicalize_json` (not dict
    iteration order) governs what gets signed.
    """
    client, _ = _evidence_client()
    ordered = _decision_evidence_body(decision_id="d-2", correlation_id="c-2")
    reordered = {key: ordered[key] for key in reversed(list(ordered))}

    ref_a = client.put_signed_evidence(
        kind="specialist_output", body=ordered, correlation_id="c-2", feature_id="F1"
    )
    ref_b = client.put_signed_evidence(
        kind="specialist_output", body=reordered, correlation_id="c-2", feature_id="F1"
    )

    assert ref_a.sha256 == ref_b.sha256
    assert ref_a.signature == ref_b.signature


def test_tampering_with_a_persisted_decision_blob_fails_verification() -> None:
    client, fake_s3 = _evidence_client()
    body = _decision_evidence_body(decision_id="d-3", correlation_id="c-3")
    ref = client.put_signed_evidence(
        kind="specialist_output", body=body, correlation_id="c-3", feature_id="F1"
    )

    original = fake_s3._objects[(ref.bucket, ref.key, ref.version_id)]
    tampered = original.replace(b"ANSWERED", b"ESCALATE")
    fake_s3._objects[(ref.bucket, ref.key, ref.version_id)] = tampered
    fake_s3._objects[(ref.bucket, ref.key, "")] = tampered

    with pytest.raises(EvidenceVerificationError):
        client.verify(ref)
