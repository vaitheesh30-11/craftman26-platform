"""KMS-signed, canonicalized evidence writer and verifier (phase-04 §3, §6-7).

Every material Sentinel action lands here: canonicalize -> sha256 ->
kms:Sign -> s3:PutObject with the signature carried as object metadata.
`verify` re-parses the stored body, re-canonicalizes it, and recomputes the
digest before asking KMS to confirm the signature -- any byte flip that
changes the body's semantic content changes the recomputed digest, so
`kms:Verify` correctly reports `SignatureValid=False` regardless of what
form the tampering took.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import boto3
from botocore.exceptions import ClientError

from iam_sentinel_adapters.errors import EvidenceVerificationError, NonRetryableError
from iam_sentinel_adapters.evidence.canonicalize import canonicalize_json
from iam_sentinel_adapters.evidence.keys import EvidenceKind, FeatureID, derive_evidence_key
from iam_sentinel_adapters.evidence.kms_signer import KmsSigner
from iam_sentinel_adapters.evidence.kms_verifier import KmsVerifier
from iam_sentinel_adapters.settings import settings

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client


@dataclass(frozen=True)
class EvidenceRef:
    bucket: str
    key: str
    version_id: str
    kms_key_arn: str
    signature: str
    sha256: str
    stored_at: datetime


class EvidenceClient:
    def __init__(
        self,
        *,
        bucket: str | None = None,
        kms_key_arn: str | None = None,
        s3_client: S3Client | None = None,
        signer: KmsSigner | None = None,
        verifier: KmsVerifier | None = None,
    ) -> None:
        self._bucket = bucket or settings.evidence_bucket
        self._kms_key_arn = kms_key_arn or settings.evidence_kms_key_arn
        self._s3: S3Client = s3_client or boto3.client("s3", region_name=settings.region)
        self._signer = signer or KmsSigner(key_arn=self._kms_key_arn)
        self._verifier = verifier or KmsVerifier()

    def put_signed_evidence(
        self,
        *,
        kind: EvidenceKind,
        body: dict[str, Any],
        correlation_id: str,
        feature_id: FeatureID,
    ) -> EvidenceRef:
        canonical_bytes = canonicalize_json(body).encode("utf-8")
        digest = hashlib.sha256(canonical_bytes).digest()
        digest_hex = digest.hex()
        signature = self._signer.sign_digest(digest)

        now = datetime.now(UTC)
        key = derive_evidence_key(
            feature_id=feature_id,
            correlation_id=correlation_id,
            kind=kind,
            body_sha256=digest_hex,
            when=now,
        )

        response = self._s3.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=canonical_bytes,
            ContentType="application/json",
            Metadata={
                "sentinel-signature": signature,
                "sentinel-sha256": digest_hex,
                "sentinel-kms-key-arn": self._kms_key_arn,
            },
        )
        return EvidenceRef(
            bucket=self._bucket,
            key=key,
            version_id=response.get("VersionId", ""),
            kms_key_arn=self._kms_key_arn,
            signature=signature,
            sha256=digest_hex,
            stored_at=now,
        )

    def verify(self, ref: EvidenceRef) -> dict[str, Any]:
        get_kwargs: dict[str, str] = {"Bucket": ref.bucket, "Key": ref.key}
        if ref.version_id:
            get_kwargs["VersionId"] = ref.version_id
        response = self._s3.get_object(**get_kwargs)  # type: ignore[arg-type]
        raw_bytes = response["Body"].read()

        try:
            parsed: dict[str, Any] = json.loads(raw_bytes)
        except json.JSONDecodeError as exc:
            raise EvidenceVerificationError(
                f"stored evidence at s3://{ref.bucket}/{ref.key} is not valid JSON"
            ) from exc

        recomputed_digest = hashlib.sha256(canonicalize_json(parsed).encode("utf-8")).digest()
        signature_bytes = base64.b64decode(ref.signature)

        if not self._verifier.verify_digest(
            key_arn=ref.kms_key_arn, digest=recomputed_digest, signature=signature_bytes
        ):
            raise EvidenceVerificationError(
                f"signature verification failed for s3://{ref.bucket}/{ref.key}"
            )

        return parsed

    def resolve_ref(self, *, bucket: str, key: str, version_id: str) -> EvidenceRef | None:
        """Reconstructs an `EvidenceRef` from just its S3 location (backend
        phase-04 §4 step 3 -- `GET /evidence/{ref}`'s `<bucket>/<key>@
        <version_id>` input has no signature attached, unlike the
        `EvidenceRef` a producer already holds in memory right after
        `put_signed_evidence`). The signature/sha256/kms_key_arn this needs
        were written as S3 object metadata by `put_signed_evidence` -- a
        `head_object` reads them without downloading the body twice.
        Returns `None` (not an exception) when the object/version does not
        exist, matching this package's "missing means None" convention
        (e.g. `ReportsClient.get_latest_cost_report`) so the caller can turn
        it into a plain 404 rather than a 500.
        """
        get_kwargs: dict[str, str] = {"Bucket": bucket, "Key": key}
        if version_id:
            get_kwargs["VersionId"] = version_id
        try:
            response = self._s3.head_object(**get_kwargs)  # type: ignore[arg-type]
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")
            if error_code in {"404", "NoSuchKey", "NoSuchVersion", "NotFound"}:
                return None
            raise NonRetryableError(f"failed to head s3://{bucket}/{key}: {exc}") from exc

        metadata = response.get("Metadata", {})
        try:
            signature = metadata["sentinel-signature"]
            sha256 = metadata["sentinel-sha256"]
            kms_key_arn = metadata["sentinel-kms-key-arn"]
        except KeyError as exc:
            raise EvidenceVerificationError(
                f"s3://{bucket}/{key} is missing required signature metadata"
            ) from exc

        stored_at = response.get("LastModified") or datetime.now(UTC)
        return EvidenceRef(
            bucket=bucket,
            key=key,
            version_id=version_id,
            kms_key_arn=kms_key_arn,
            signature=signature,
            sha256=sha256,
            stored_at=stored_at,
        )

    def verify_by_location(
        self, *, bucket: str, key: str, version_id: str
    ) -> dict[str, Any] | None:
        """Resolves + verifies in one call -- the composition `GET
        /evidence/{ref}` needs. `None` means "not found" (404); a raised
        `EvidenceVerificationError` means "found but tampered" (502) -- the
        two failure modes the spec's endpoint contract distinguishes.
        """
        ref = self.resolve_ref(bucket=bucket, key=key, version_id=version_id)
        if ref is None:
            return None
        return self.verify(ref)
