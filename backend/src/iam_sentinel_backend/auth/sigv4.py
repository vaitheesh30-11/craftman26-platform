"""IAM SigV4 verifier (phase-00 §3, §7 risk mitigation).

Two paths, per the spec:

1. **API Gateway pass-through (primary).** When IAM auth is configured on
   the route, API Gateway verifies the SigV4 signature itself and hands
   Lambda the already-verified caller ARN in
   `event.requestContext.identity.userArn`. No STS call needed --
   `from_apigw_identity` just trusts that field.
2. **Relayed `GetCallerIdentity` (fallback).** Used only for WebSocket auth
   and local dev, where there is no API Gateway IAM authorizer in front of
   the request. The caller presigns a `GetCallerIdentity` call themselves
   and hands over the resulting headers; `verify_signed_headers` relays
   them to STS via `iam_sentinel_adapters.sts.StsClient` and trusts only
   STS's own signature check. Result cached 5 min per phase-00 §3.
"""

from __future__ import annotations

import time
from threading import Lock

from iam_sentinel_adapters.errors import SentinelAdapterError
from iam_sentinel_adapters.sts import StsClient

from iam_sentinel_backend.auth.principal import Principal
from iam_sentinel_backend.settings import settings


class SigV4VerificationError(Exception):
    """Raised when a presented SigV4 request fails identity verification."""


def from_apigw_identity(user_arn: str) -> Principal:
    """Trust API Gateway's own IAM-auth pass-through (path 1 above)."""
    if not user_arn:
        raise SigV4VerificationError("apigw identity.userArn is empty")
    return Principal(arn=user_arn, groups=(), auth_kind="sigv4")


class SigV4Verifier:
    """Relays a caller-presigned `GetCallerIdentity` request to STS
    (path 2 above), caching the resolved identity per signed-headers digest
    for `settings.sigv4_caller_identity_ttl_seconds`.
    """

    def __init__(self, *, sts_client: StsClient | None = None) -> None:
        self._sts = sts_client or StsClient()
        self._lock = Lock()
        self._cache: dict[str, tuple[Principal, float]] = {}

    def verify_signed_headers(self, headers: dict[str, str]) -> Principal:
        cache_key = headers.get("Authorization", "")
        now = time.monotonic()

        with self._lock:
            cached = self._cache.get(cache_key)
            if cached is not None and now - cached[1] < settings.sigv4_caller_identity_ttl_seconds:
                return cached[0]

        try:
            identity = self._sts.verify_signed_request(headers=headers)
        except SentinelAdapterError as exc:
            raise SigV4VerificationError(str(exc)) from exc

        principal = Principal(arn=identity["arn"], groups=(), auth_kind="sigv4")
        with self._lock:
            self._cache[cache_key] = (principal, now)
        return principal
