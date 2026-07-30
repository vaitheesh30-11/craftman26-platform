from __future__ import annotations

import json
from unittest.mock import MagicMock

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from iam_sentinel_backend.auth.cognito import CognitoJwtVerifier, CognitoVerificationError
from iam_sentinel_backend.settings import settings


@pytest.fixture
def rsa_keypair() -> tuple[rsa.RSAPrivateKey, dict[str, object]]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = json.loads(RSAAlgorithm.to_jwk(private_key.public_key()))
    public_jwk["kid"] = "test-kid-1"
    public_jwk["use"] = "sig"
    public_jwk["alg"] = "RS256"
    return private_key, public_jwk


def _fake_jwks_response(keys: list[dict[str, object]]) -> MagicMock:
    response = MagicMock()
    response.json.return_value = {"keys": keys}
    response.raise_for_status.return_value = None
    return response


def test_verify_accepts_a_validly_signed_token(
    rsa_keypair: tuple[rsa.RSAPrivateKey, dict[str, object]],
) -> None:
    private_key, public_jwk = rsa_keypair
    token = jwt.encode(
        {"sub": "user-123", "email": "alice@example.com", "cognito:groups": ["SentinelAuditors"]},
        private_key,
        algorithm="RS256",
        headers={"kid": "test-kid-1"},
    )
    session = MagicMock()
    session.get.return_value = _fake_jwks_response([public_jwk])
    verifier = CognitoJwtVerifier(session=session)
    settings.cognito_user_pool_id = "us-east-1_TESTPOOL"

    principal = verifier.verify(token)

    assert principal.arn.endswith("userpool/us-east-1_TESTPOOL/user-123")
    assert principal.auth_kind == "cognito"
    assert principal.groups == ("SentinelAuditors",)
    assert principal.email == "alice@example.com"


def test_verify_rejects_a_tampered_token(
    rsa_keypair: tuple[rsa.RSAPrivateKey, dict[str, object]],
) -> None:
    private_key, public_jwk = rsa_keypair
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = jwt.encode(
        {"sub": "user-123"}, other_key, algorithm="RS256", headers={"kid": "test-kid-1"}
    )
    session = MagicMock()
    session.get.return_value = _fake_jwks_response([public_jwk])
    verifier = CognitoJwtVerifier(session=session)

    with pytest.raises(CognitoVerificationError):
        verifier.verify(token)


def test_verify_rejects_an_expired_token(
    rsa_keypair: tuple[rsa.RSAPrivateKey, dict[str, object]],
) -> None:
    private_key, public_jwk = rsa_keypair
    token = jwt.encode(
        {"sub": "user-123", "exp": 1},  # 1970 -- long expired
        private_key,
        algorithm="RS256",
        headers={"kid": "test-kid-1"},
    )
    session = MagicMock()
    session.get.return_value = _fake_jwks_response([public_jwk])
    verifier = CognitoJwtVerifier(session=session)

    with pytest.raises(CognitoVerificationError):
        verifier.verify(token)


def test_verify_rejects_unknown_kid(
    rsa_keypair: tuple[rsa.RSAPrivateKey, dict[str, object]],
) -> None:
    private_key, _ = rsa_keypair
    token = jwt.encode(
        {"sub": "user-123"}, private_key, algorithm="RS256", headers={"kid": "no-such-kid"}
    )
    session = MagicMock()
    session.get.return_value = _fake_jwks_response([])
    verifier = CognitoJwtVerifier(session=session)

    with pytest.raises(CognitoVerificationError):
        verifier.verify(token)


def test_jwks_is_cached_across_calls(
    rsa_keypair: tuple[rsa.RSAPrivateKey, dict[str, object]],
) -> None:
    private_key, public_jwk = rsa_keypair
    token = jwt.encode(
        {"sub": "user-123"}, private_key, algorithm="RS256", headers={"kid": "test-kid-1"}
    )
    session = MagicMock()
    session.get.return_value = _fake_jwks_response([public_jwk])
    verifier = CognitoJwtVerifier(session=session)

    verifier.verify(token)
    verifier.verify(token)

    assert session.get.call_count == 1
