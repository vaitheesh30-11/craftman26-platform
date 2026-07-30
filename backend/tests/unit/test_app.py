from __future__ import annotations

from fastapi.testclient import TestClient

from iam_sentinel_backend.app import create_app, handler

_ULID_RE_LEN = 26


def test_health_returns_200_with_no_auth() -> None:
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body == {"ok": True, "data": {"stage": "dev", "commit": "unknown"}}


def test_health_response_carries_a_correlation_id_header() -> None:
    client = TestClient(create_app())

    response = client.get("/health")

    correlation_id = response.headers["X-Correlation-Id"]
    assert len(correlation_id) == _ULID_RE_LEN


def test_correlation_id_is_echoed_back_when_caller_supplies_one() -> None:
    client = TestClient(create_app())
    supplied = "01ARZ3NDEKTSV4RRFFQ69G5FAV"

    response = client.get("/health", headers={"X-Correlation-Id": supplied})

    assert response.headers["X-Correlation-Id"] == supplied


def test_correlation_id_is_regenerated_when_malformed() -> None:
    client = TestClient(create_app())

    response = client.get("/health", headers={"X-Correlation-Id": "not-a-ulid"})

    assert response.headers["X-Correlation-Id"] != "not-a-ulid"
    assert len(response.headers["X-Correlation-Id"]) == _ULID_RE_LEN


def test_mangum_handler_is_wired_for_lambda() -> None:
    assert callable(handler)
