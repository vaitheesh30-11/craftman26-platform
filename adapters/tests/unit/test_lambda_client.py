from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from iam_sentinel_adapters.compute.lambda_client import LambdaInvocationError, LambdaInvokeClient
from iam_sentinel_adapters.errors import ValidationError


def _invoke_response(
    payload: dict[str, object], *, function_error: str | None = None
) -> dict[str, object]:
    response: dict[str, object] = {"Payload": BytesIO(json.dumps(payload).encode("utf-8"))}
    if function_error is not None:
        response["FunctionError"] = function_error
    return response


def test_invoke_returns_parsed_payload() -> None:
    mock_client = MagicMock()
    mock_client.invoke.return_value = _invoke_response({"verdict": "CONFIRM"})
    client = LambdaInvokeClient(lambda_client=mock_client)

    result = client.invoke("sentinel-router", {"mode": "fast"})

    assert result == {"verdict": "CONFIRM"}
    mock_client.invoke.assert_called_once()


def test_invoke_raises_on_function_error() -> None:
    mock_client = MagicMock()
    mock_client.invoke.return_value = _invoke_response(
        {"errorMessage": "boom"}, function_error="Unhandled"
    )
    client = LambdaInvokeClient(lambda_client=mock_client)

    with pytest.raises(LambdaInvocationError):
        client.invoke("sentinel-router", {})


def test_invoke_maps_resource_not_found_to_validation_error() -> None:
    mock_client = MagicMock()
    mock_client.invoke.side_effect = ClientError(
        {"Error": {"Code": "ResourceNotFoundException", "Message": "no such function"}}, "Invoke"
    )
    client = LambdaInvokeClient(lambda_client=mock_client)

    with pytest.raises(ValidationError):
        client.invoke("does-not-exist", {})
