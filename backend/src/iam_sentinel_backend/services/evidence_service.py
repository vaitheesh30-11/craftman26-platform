"""`GET /evidence/{ref}` (backend phase-04 §2-5). `ref` is `<bucket>/<key>@
<version_id>` per the spec's own grammar -- `derive_evidence_key` (adapters
phase-04) never emits a key containing `@`, and S3 bucket names can't
contain `/`, so splitting on the last `@` then the first `/` is unambiguous
for every ref this platform itself ever mints.

Access control per phase-04 §5: only `SentinelAuditors`/`SentinelOperators`
(plus SigV4 machine callers, same "not a human end-user" reasoning
`findings_service._is_privileged` already applies) may read evidence at
all -- every other group gets no evidence access, full stop, not even
scoped to their own principal (evidence blobs have no principal_arn to
scope by in the first place).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import status

from iam_sentinel_backend.errors import SentinelHTTPException
from iam_sentinel_backend.settings import settings

if TYPE_CHECKING:
    from typing import Any

    from iam_sentinel_adapters.evidence.client import EvidenceClient

    from iam_sentinel_backend.auth.principal import Principal


def _is_privileged(principal: Principal) -> bool:
    return (
        principal.auth_kind == "sigv4"
        or principal.is_in_group(settings.cognito_group_auditors)
        or principal.is_in_group(settings.cognito_group_operators)
    )


def parse_evidence_ref(ref: str) -> tuple[str, str, str]:
    location, sep, version_id = ref.rpartition("@")
    if not sep or not version_id:
        raise SentinelHTTPException(
            code="INVALID_EVIDENCE_REF",
            message="ref must be '<bucket>/<key>@<version_id>'",
            http_status=status.HTTP_400_BAD_REQUEST,
        )
    bucket, sep, key = location.partition("/")
    if not sep or not bucket or not key:
        raise SentinelHTTPException(
            code="INVALID_EVIDENCE_REF",
            message="ref must be '<bucket>/<key>@<version_id>'",
            http_status=status.HTTP_400_BAD_REQUEST,
        )
    return bucket, key, version_id


class EvidenceService:
    def __init__(self, evidence_client: EvidenceClient) -> None:
        self._evidence = evidence_client

    def get_evidence(self, *, principal: Principal, ref: str) -> dict[str, Any]:
        if not _is_privileged(principal):
            raise SentinelHTTPException(
                code="ACCESS_DENIED",
                message="evidence access requires SentinelAuditors or SentinelOperators group "
                "membership",
                http_status=status.HTTP_403_FORBIDDEN,
            )

        bucket, key, version_id = parse_evidence_ref(ref)
        # `EvidenceVerificationError` (tampered/corrupt) is deliberately not
        # caught here -- it propagates to `errors.py`'s global handler,
        # mapped to 502 per phase-04 §4 step 3 "return body only on valid;
        # else 502".
        body = self._evidence.verify_by_location(bucket=bucket, key=key, version_id=version_id)
        if body is None:
            raise SentinelHTTPException(
                code="EVIDENCE_NOT_FOUND",
                message=f"no evidence object at s3://{bucket}/{key}@{version_id}",
                http_status=status.HTTP_404_NOT_FOUND,
            )
        return body
