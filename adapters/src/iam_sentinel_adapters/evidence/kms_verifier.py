"""`kms:Verify` wrapper with a 1-hour in-process public-key cache
(phase-04 §7).

Verification itself always goes through the `kms:Verify` API rather than a
local RSASSA-PSS implementation: AWS KMS's PSS salt length (fixed at the
hash's digest length, not the more common "maximum possible" convention
many PSS libraries default to) is a well-known interop trap, and a
client-side re-implementation that got that parameter wrong would fail
silently rather than raise. `get_public_key` is a separate, independently
useful capability (e.g. for publishing the key so a third party can verify
without AWS access) — it is cached but never substituted for the
authoritative `kms:Verify` call.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Literal

import boto3

from iam_sentinel_adapters.settings import settings

if TYPE_CHECKING:
    from mypy_boto3_kms import KMSClient

_SIGNING_ALGORITHM: Literal["RSASSA_PSS_SHA_256"] = "RSASSA_PSS_SHA_256"
_MESSAGE_TYPE: Literal["DIGEST"] = "DIGEST"
_PUBLIC_KEY_CACHE_TTL_SECONDS = 3600.0


class KmsVerifier:
    def __init__(self, *, client: KMSClient | None = None) -> None:
        self._kms: KMSClient = client or boto3.client("kms", region_name=settings.region)
        self._public_key_cache: dict[str, tuple[bytes, float]] = {}

    def verify_digest(self, *, key_arn: str, digest: bytes, signature: bytes) -> bool:
        response = self._kms.verify(
            KeyId=key_arn,
            Message=digest,
            MessageType=_MESSAGE_TYPE,
            Signature=signature,
            SigningAlgorithm=_SIGNING_ALGORITHM,
        )
        return bool(response["SignatureValid"])

    def get_public_key(self, key_arn: str) -> bytes:
        now = time.monotonic()
        cached = self._public_key_cache.get(key_arn)
        if cached is not None and now - cached[1] < _PUBLIC_KEY_CACHE_TTL_SECONDS:
            return cached[0]

        response = self._kms.get_public_key(KeyId=key_arn)
        public_key = bytes(response["PublicKey"])
        self._public_key_cache[key_arn] = (public_key, now)
        return public_key
