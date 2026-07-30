"""End-to-end router wiring via `TestClient` + dependency overrides
(backend phase-01 §8: "Auth: 401 for unauthenticated, 403 for
cross-principal reads"). Service-level logic already has focused unit
coverage (`test_findings_service.py` et al.); these tests verify the HTTP
layer actually enforces what the services decide.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from iam_sentinel_backend import deps
from iam_sentinel_backend.app import create_app
from iam_sentinel_backend.auth.principal import Principal
from iam_sentinel_backend.errors import SentinelHTTPException
from iam_sentinel_backend.schemas.router_bridge import FastPathResponse

_PRINCIPAL = Principal(arn="arn:aws:iam::111122223333:role/Alice", auth_kind="cognito")


def test_findings_requires_authentication() -> None:
    client = TestClient(create_app())

    response = client.get("/findings")

    assert response.status_code == 401


def test_findings_propagates_a_service_level_access_denial() -> None:
    app = create_app()
    mock_service = MagicMock()
    mock_service.list_findings.side_effect = SentinelHTTPException(
        code="ACCESS_DENIED", message="denied", http_status=403
    )
    app.dependency_overrides[deps.get_principal] = lambda: _PRINCIPAL
    app.dependency_overrides[deps.get_findings_service] = lambda: mock_service
    client = TestClient(app)

    response = client.get(
        "/findings", params={"principal_arn": "arn:aws:iam::111122223333:role/Bob"}
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ACCESS_DENIED"


def test_emergency_kill_session_refuses_without_breakglass_tag() -> None:
    app = create_app()
    app.dependency_overrides[deps.get_principal] = lambda: _PRINCIPAL
    client = TestClient(app)

    response = client.post("/emergency/kill-session", json={"payload": {"role_arn": "x"}})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "BREAKGLASS_REQUIRED"


def test_emergency_kill_session_succeeds_with_a_valid_breakglass_tag() -> None:
    app = create_app()
    mock_service = MagicMock()
    mock_service.dispatch.return_value = FastPathResponse(
        target="F5", verdict="CONFIRM", reason="session killed"
    )
    app.dependency_overrides[deps.get_principal] = lambda: _PRINCIPAL
    app.dependency_overrides[deps.get_router_bridge_service] = lambda: mock_service
    client = TestClient(app)

    response = client.post(
        "/emergency/kill-session",
        json={"payload": {"role_arn": "x"}},
        headers={"X-BreakGlass-Session-Tag": "BreakGlass=IAMSentinel-Two-Signer"},
    )

    assert response.status_code == 200
    mock_service.dispatch.assert_called_once()


def test_monitor_shadow_violations_is_a_get_route() -> None:
    app = create_app()
    mock_service = MagicMock()
    mock_service.dispatch_read.return_value = {"items": []}
    app.dependency_overrides[deps.get_principal] = lambda: _PRINCIPAL
    app.dependency_overrides[deps.get_router_bridge_service] = lambda: mock_service
    client = TestClient(app)

    response = client.get("/monitor/shadow-violations")

    assert response.status_code == 200
    assert response.json()["data"] == {"items": []}
