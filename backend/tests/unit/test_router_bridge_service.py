from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from iam_sentinel_adapters.errors import ValidationError

from iam_sentinel_backend.auth.principal import Principal
from iam_sentinel_backend.errors import SentinelHTTPException
from iam_sentinel_backend.services.router_bridge_service import RouterBridgeService

_PRINCIPAL = Principal(arn="arn:aws:iam::111122223333:role/Alice", auth_kind="cognito")


def test_dispatch_returns_a_fast_path_response() -> None:
    lambda_client = MagicMock()
    lambda_client.invoke.return_value = {
        "verdict": "CONFIRM",
        "reason": "over-privileged",
        "findings": [],
    }
    service = RouterBridgeService(lambda_client, function_name="sentinel-router")

    result = service.dispatch(
        target="F1", payload={"role_arn": "x"}, principal=_PRINCIPAL, correlation_id="c1"
    )

    assert result.verdict == "CONFIRM"
    assert result.target == "F1"


def test_dispatch_maps_adapter_errors_to_502() -> None:
    lambda_client = MagicMock()
    lambda_client.invoke.side_effect = ValidationError("no such function")
    service = RouterBridgeService(lambda_client, function_name="sentinel-router")

    with pytest.raises(SentinelHTTPException) as exc_info:
        service.dispatch(target="F1", payload={}, principal=_PRINCIPAL, correlation_id="c1")

    assert exc_info.value.status_code == 502


def test_dispatch_read_invokes_with_the_read_shaped_payload() -> None:
    lambda_client = MagicMock()
    lambda_client.invoke.return_value = {"items": []}
    service = RouterBridgeService(lambda_client, function_name="sentinel-router")

    result = service.dispatch_read(target="F6", query={"account_id": "111122223333"})

    assert result == {"items": []}
    lambda_client.invoke.assert_called_once_with(
        "sentinel-router", {"mode": "fast", "target": "F6", "query": {"account_id": "111122223333"}}
    )
