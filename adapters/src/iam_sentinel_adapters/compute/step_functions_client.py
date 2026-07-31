"""Synchronous `states:StartSyncExecution` wrapper for the
`SentinelApprovalApply` Standard workflow (backend phase-03 §3-4). The state
machine itself -- ASL definition + CDK wiring -- is `aws-infra`'s
deliverable per this repo's established module boundary (CDK lives in
`aws-infra/`, `backend/` only calls AWS through `adapters/`), and it has not
been built yet. This client is built against the documented request/output
contract now, the same "build the caller before the callee exists"
precedent as `LambdaInvokeClient` (ADR 0018 decision 1) and `aws-infra`
phase-08's cross-account StackSets (ADR 0014). Invoking an ARN Step
Functions doesn't recognize surfaces as `StateMachineDoesNotExist` ->
`ValidationError`, never a raw boto3 exception; an execution that itself
ends `FAILED`/`TIMED_OUT`/`ABORTED` (as opposed to `SUCCEEDED` with a
business-level `state` of `REJECTED`/`ROLLED_BACK` in its JSON output)
raises `StepFunctionsExecutionFailedError`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import boto3
from botocore.exceptions import ClientError

from iam_sentinel_adapters.errors import NonRetryableError, ThrottlingError, ValidationError
from iam_sentinel_adapters.retry import Policy, retry
from iam_sentinel_adapters.settings import settings

if TYPE_CHECKING:
    from mypy_boto3_stepfunctions import SFNClient

_THROTTLE_CODES = {"TooManyRequestsException", "ThrottlingException"}
_NOT_FOUND_CODES = {"StateMachineDoesNotExist"}


class StepFunctionsExecutionFailedError(NonRetryableError):
    """The synchronous execution itself ended `FAILED`/`TIMED_OUT`/`ABORTED`
    (transport-level success, business-level failure the state machine
    itself never reached a business `state` for).
    """


@dataclass(frozen=True)
class SyncExecutionResult:
    execution_arn: str
    output: dict[str, Any]


class StepFunctionsClient:
    def __init__(self, *, sfn_client: SFNClient | None = None) -> None:
        self._sfn: SFNClient = sfn_client or boto3.client(
            "stepfunctions", region_name=settings.region
        )

    def start_sync_execution(
        self,
        *,
        state_machine_arn: str,
        input_payload: dict[str, Any],
        name: str | None = None,
    ) -> SyncExecutionResult:
        response = self._start_sync_execution(
            state_machine_arn=state_machine_arn,
            name=name,
            input_json=json.dumps(input_payload),
        )
        execution_arn = str(response.get("executionArn", ""))
        exec_status = response.get("status")
        if exec_status != "SUCCEEDED":
            raise StepFunctionsExecutionFailedError(
                f"{state_machine_arn} execution {execution_arn or '?'} ended "
                f"{exec_status}: {response.get('error')} {response.get('cause')}"
            )
        raw_output = response.get("output")
        output: dict[str, Any] = json.loads(raw_output) if raw_output else {}
        return SyncExecutionResult(execution_arn=execution_arn, output=output)

    @retry(policy=Policy.CAUTIOUS, retry_on=(ThrottlingError,))
    def _start_sync_execution(
        self, *, state_machine_arn: str, name: str | None, input_json: str
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"stateMachineArn": state_machine_arn, "input": input_json}
        if name is not None:
            kwargs["name"] = name
        try:
            return dict(self._sfn.start_sync_execution(**kwargs))
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in _THROTTLE_CODES:
                raise ThrottlingError(str(exc)) from exc
            if code in _NOT_FOUND_CODES:
                raise ValidationError(f"{state_machine_arn} does not exist: {exc}") from exc
            raise NonRetryableError(str(exc)) from exc
