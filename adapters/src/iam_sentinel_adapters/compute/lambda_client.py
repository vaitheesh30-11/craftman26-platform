"""Synchronous `lambda:Invoke` wrapper (backend phase-01 §5, Router Bridge
Contract). `functions/router` (agents phase-15 dual-mode) is the callee --
it does not exist yet (Wave 8, sprint step 40), same "build the caller
against the documented contract before the callee exists" precedent as
`aws-infra` phase-08's cross-account StackSets (ADR 0014) and phase-07's
`backend_api` shim (ADR 0017). Invoking a function name AWS Lambda doesn't
recognize surfaces as `ResourceNotFoundException` -> `ValidationError`,
which `backend/errors.py` maps to a 400, not a leaked 500.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import boto3
from botocore.exceptions import ClientError

from iam_sentinel_adapters.errors import (
    NonRetryableError,
    SentinelAdapterError,
    ThrottlingError,
    ValidationError,
)
from iam_sentinel_adapters.retry import Policy, retry
from iam_sentinel_adapters.settings import settings

if TYPE_CHECKING:
    from mypy_boto3_lambda import LambdaClient

_THROTTLE_CODES = {"TooManyRequestsException"}
_NOT_FOUND_CODES = {"ResourceNotFoundException"}


class LambdaInvocationError(SentinelAdapterError):
    """The invoked function itself returned `FunctionError` (unhandled
    exception inside the callee, not a transport/throttling failure).
    """


class LambdaInvokeClient:
    def __init__(self, *, lambda_client: LambdaClient | None = None) -> None:
        self._lambda: LambdaClient = lambda_client or boto3.client(
            "lambda", region_name=settings.region
        )

    def invoke(self, function_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._invoke(function_name, payload)
        raw_payload = response["Payload"].read()
        body: dict[str, Any] = json.loads(raw_payload) if raw_payload else {}
        if response.get("FunctionError"):
            raise LambdaInvocationError(
                f"{function_name} raised {response['FunctionError']}: {body}"
            )
        return body

    @retry(policy=Policy.AGGRESSIVE, retry_on=(ThrottlingError,))
    def _invoke(self, function_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return dict(
                self._lambda.invoke(
                    FunctionName=function_name,
                    InvocationType="RequestResponse",
                    Payload=json.dumps(payload).encode("utf-8"),
                )
            )
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in _THROTTLE_CODES:
                raise ThrottlingError(str(exc)) from exc
            if code in _NOT_FOUND_CODES:
                raise ValidationError(f"{function_name} is not a deployed function: {exc}") from exc
            raise NonRetryableError(str(exc)) from exc
