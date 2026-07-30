from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from iam_sentinel_backend import deps
from iam_sentinel_backend.auth.principal import Principal
from iam_sentinel_backend.errors import register_exception_handlers


@pytest.fixture
def app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/whoami")
    def _whoami(principal: Principal = Depends(deps.get_principal)) -> dict[str, str]:
        return {"arn": principal.arn, "auth_kind": principal.auth_kind}

    return app


def test_get_principal_rejects_missing_authorization(app: FastAPI) -> None:
    client = TestClient(app)

    response = client.get("/whoami")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_get_principal_trusts_apigw_reflected_identity(app: FastAPI) -> None:
    client = TestClient(app)

    # Simplest reliable way to inject `scope["aws.event"]` without a real
    # API Gateway request: monkeypatch the helper directly.
    original = deps._apigw_user_arn
    deps._apigw_user_arn = lambda request: "arn:aws:iam::111122223333:role/machine"  # type: ignore[assignment]
    try:
        response = client.get("/whoami")
    finally:
        deps._apigw_user_arn = original  # type: ignore[assignment]

    assert response.status_code == 200
    assert response.json()["arn"] == "arn:aws:iam::111122223333:role/machine"
    assert response.json()["auth_kind"] == "sigv4"


def test_get_principal_uses_sigv4_relay_for_aws4_authorization(app: FastAPI) -> None:
    client = TestClient(app)
    fake_principal = Principal(
        arn="arn:aws:iam::111122223333:user/bob", groups=(), auth_kind="sigv4"
    )
    original_verify = deps._sigv4_verifier.verify_signed_headers
    deps._sigv4_verifier.verify_signed_headers = MagicMock(return_value=fake_principal)  # type: ignore[method-assign]
    try:
        response = client.get(
            "/whoami", headers={"Authorization": "AWS4-HMAC-SHA256 Credential=..."}
        )
    finally:
        deps._sigv4_verifier.verify_signed_headers = original_verify  # type: ignore[method-assign]

    assert response.status_code == 200
    assert response.json()["arn"] == "arn:aws:iam::111122223333:user/bob"


def test_get_principal_uses_cognito_for_bearer_token(app: FastAPI) -> None:
    client = TestClient(app)
    fake_principal = Principal(
        arn="arn:aws:cognito-idp:us-east-1:111122223333:userpool/pool/sub-1", auth_kind="cognito"
    )
    original_verify = deps._cognito_verifier.verify
    deps._cognito_verifier.verify = MagicMock(return_value=fake_principal)  # type: ignore[method-assign]
    try:
        response = client.get("/whoami", headers={"Authorization": "Bearer sometoken"})
    finally:
        deps._cognito_verifier.verify = original_verify  # type: ignore[method-assign]

    assert response.status_code == 200
    assert response.json()["auth_kind"] == "cognito"


def test_get_correlation_id_raises_when_state_missing() -> None:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/needs-correlation")
    def _needs_correlation(
        correlation_id: str = Depends(deps.get_correlation_id),
    ) -> dict[str, str]:
        return {"correlation_id": correlation_id}

    client = TestClient(app)

    response = client.get("/needs-correlation")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "MISSING_CORRELATION_ID"


def test_lru_cached_adapter_deps_return_singletons() -> None:
    first = deps.get_findings_client()
    second = deps.get_findings_client()

    assert first is second
