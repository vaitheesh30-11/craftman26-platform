from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from iam_sentinel_adapters.errors import (
    AccessDeniedError,
    BudgetExceededError,
    CircuitOpenError,
    SanitizerRejection,
)

from iam_sentinel_backend.errors import register_exception_handlers, SentinelHTTPException


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom/sanitizer")
    def _boom_sanitizer() -> None:
        raise SanitizerRejection("forbidden pattern detected")

    @app.get("/boom/access-denied")
    def _boom_access_denied() -> None:
        raise AccessDeniedError("caller lacks permission")

    @app.get("/boom/budget")
    def _boom_budget() -> None:
        raise BudgetExceededError("over cap")

    @app.get("/boom/circuit")
    def _boom_circuit() -> None:
        raise CircuitOpenError("breaker open")

    @app.get("/boom/sentinel-http")
    def _boom_sentinel_http() -> None:
        raise SentinelHTTPException(code="CUSTOM_CODE", message="custom message", http_status=418)

    @app.get("/boom/unhandled")
    def _boom_unhandled() -> None:
        raise RuntimeError("something broke")

    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize(
    ("path", "expected_status", "expected_code"),
    [
        ("/boom/sanitizer", 400, "SANITIZER_REJECTION"),
        ("/boom/access-denied", 403, "ACCESS_DENIED"),
        ("/boom/budget", 429, "BUDGET_EXCEEDED"),
        ("/boom/circuit", 503, "CIRCUIT_OPEN"),
        ("/boom/sentinel-http", 418, "CUSTOM_CODE"),
    ],
)
def test_domain_exceptions_map_to_the_documented_status_and_code(
    client: TestClient, path: str, expected_status: int, expected_code: str
) -> None:
    response = client.get(path)

    assert response.status_code == expected_status
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == expected_code


def test_unhandled_exception_returns_500_without_leaking_the_traceback(client: TestClient) -> None:
    response = client.get("/boom/unhandled")

    assert response.status_code == 500
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert "RuntimeError" not in body["error"]["message"]
    assert "something broke" not in body["error"]["message"]
