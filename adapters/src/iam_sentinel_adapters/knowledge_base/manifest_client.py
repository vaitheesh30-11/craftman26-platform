"""KMS-signed KB quote-manifest reader/writer (agents phase-10 §3, §6).

Mirrors `evidence/client.py`'s canonicalize -> sha256 -> kms:Sign|Verify
pattern. The manifest body itself (sentence tokenization, span windowing,
per-quote hashing) is pure Python living in `iam_sentinel_agents.knowledge_base`
-- no AWS calls there. This client owns only the S3/KMS boundary: signing the
already-computed digest, persisting the signed body, and verifying + reading
it back. `manifest_sha256` is signed directly as a KMS `MessageType=DIGEST`
input (it is already a sha256 digest, per the interface contract) rather than
re-hashed here.
"""

from __future__ import annotations

import base64
import json
from typing import TYPE_CHECKING, Any

import boto3

from iam_sentinel_adapters.errors import ManifestVerificationError
from iam_sentinel_adapters.evidence.kms_signer import KmsSigner
from iam_sentinel_adapters.evidence.kms_verifier import KmsVerifier
from iam_sentinel_adapters.settings import settings

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client


class KbManifestClient:
    def __init__(
        self,
        *,
        bucket: str | None = None,
        key: str | None = None,
        kms_key_arn: str | None = None,
        s3_client: S3Client | None = None,
        signer: KmsSigner | None = None,
        verifier: KmsVerifier | None = None,
    ) -> None:
        self._bucket = bucket or settings.kb_manifest_bucket
        self._key = key or settings.kb_manifest_key
        self.kms_key_arn = kms_key_arn or settings.kb_manifest_kms_key_arn
        self._s3: S3Client = s3_client or boto3.client("s3", region_name=settings.region)
        self._signer = signer or KmsSigner(key_arn=self.kms_key_arn)
        self._verifier = verifier or KmsVerifier()

    def sign(self, manifest_sha256_digest: bytes) -> str:
        return self._signer.sign_digest(manifest_sha256_digest)

    def put(self, *, body: dict[str, Any], version_key: str | None = None) -> None:
        payload = json.dumps(body).encode("utf-8")
        self._s3.put_object(
            Bucket=self._bucket, Key=self._key, Body=payload, ContentType="application/json"
        )
        if version_key:
            self._s3.put_object(
                Bucket=self._bucket, Key=version_key, Body=payload, ContentType="application/json"
            )

    def get_verified(self) -> dict[str, Any]:
        response = self._s3.get_object(Bucket=self._bucket, Key=self._key)
        raw_bytes = response["Body"].read()

        try:
            parsed: dict[str, Any] = json.loads(raw_bytes)
        except json.JSONDecodeError as exc:
            raise ManifestVerificationError(
                f"manifest at s3://{self._bucket}/{self._key} is not valid JSON"
            ) from exc

        digest = bytes.fromhex(parsed["manifest_sha256"])
        signature = base64.b64decode(parsed["signature"])
        if not self._verifier.verify_digest(
            key_arn=parsed["kms_key_arn"], digest=digest, signature=signature
        ):
            raise ManifestVerificationError(
                f"signature verification failed for s3://{self._bucket}/{self._key}"
            )
        return parsed
