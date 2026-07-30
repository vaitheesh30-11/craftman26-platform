"""Cognito JWT verifier (phase-00 §3-4).

Verifies against the pool's published JWKS (RS256), cached in-process for
`settings.cognito_jwks_ttl_seconds` (15 min default). `sub`, `email`,
`cognito:groups` are extracted; `principal` is a synthetic ARN
(`arn:aws:cognito-idp:<region>:<account>:userpool/<pool-id>/<sub>`) per
phase-00 §3 -- Cognito has no real IAM ARN for a user pool member.
"""

from __future__ import annotations

import time
from threading import Lock
from typing import Any

import jwt
import requests
from jwt.algorithms import RSAAlgorithm

from iam_sentinel_backend.auth.principal import Principal
from iam_sentinel_backend.settings import settings

_JWKS_FETCH_TIMEOUT_SECONDS = 5.0


class CognitoVerificationError(Exception):
    """Raised when a presented Cognito JWT fails verification for any reason."""


class CognitoJwtVerifier:
    def __init__(self, *, session: requests.Session | None = None) -> None:
        self._session = session or requests.Session()
        self._lock = Lock()
        self._jwks_cache: dict[str, Any] | None = None
        self._jwks_fetched_at_monotonic: float = 0.0

    def _jwks_url(self) -> str:
        return (
            f"https://cognito-idp.{settings.region}.amazonaws.com/"
            f"{settings.cognito_user_pool_id}/.well-known/jwks.json"
        )

    def _get_jwks(self) -> dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            fresh = self._jwks_cache is not None and (
                now - self._jwks_fetched_at_monotonic < settings.cognito_jwks_ttl_seconds
            )
            if fresh and self._jwks_cache is not None:
                return self._jwks_cache

        try:
            response = self._session.get(self._jwks_url(), timeout=_JWKS_FETCH_TIMEOUT_SECONDS)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise CognitoVerificationError(f"failed to fetch JWKS: {exc}") from exc

        jwks: dict[str, Any] = response.json()
        with self._lock:
            self._jwks_cache = jwks
            self._jwks_fetched_at_monotonic = now
        return jwks

    def _signing_key(self, token: str) -> Any:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.InvalidTokenError as exc:
            raise CognitoVerificationError(f"malformed token header: {exc}") from exc

        kid = header.get("kid")
        jwks = self._get_jwks()
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                return RSAAlgorithm.from_jwk(key)
        raise CognitoVerificationError(f"no matching JWK for kid={kid!r}")

    def verify(self, token: str) -> Principal:
        signing_key = self._signing_key(token)
        try:
            claims = jwt.decode(
                token,
                key=signing_key,
                algorithms=["RS256"],
                audience=settings.cognito_app_client_id or None,
                options={"verify_aud": bool(settings.cognito_app_client_id)},
            )
        except jwt.InvalidTokenError as exc:
            raise CognitoVerificationError(str(exc)) from exc

        sub = claims.get("sub")
        if not sub:
            raise CognitoVerificationError("token missing required 'sub' claim")

        groups = tuple(claims.get("cognito:groups", []))
        arn = (
            f"arn:aws:cognito-idp:{settings.region}:{settings.aws_account_id}:"
            f"userpool/{settings.cognito_user_pool_id}/{sub}"
        )
        return Principal(arn=arn, groups=groups, auth_kind="cognito", email=claims.get("email"))
