from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from iam_sentinel_adapters.compute.step_functions_client import (
    StepFunctionsClient,
    StepFunctionsExecutionFailedError,
)
from iam_sentinel_adapters.errors import ValidationError

_ARN = "arn:aws:states:us-east-1:111122223333:stateMachine:SentinelApprovalApply"


def test_start_sync_execution_returns_parsed_output_on_success() -> None:
    mock_sfn = MagicMock()
    mock_sfn.start_sync_execution.return_value = {
        "executionArn": "arn:aws:states:...:execution:abc",
        "status": "SUCCEEDED",
        "output": json.dumps({"state": "SUCCEEDED"}),
    }
    client = StepFunctionsClient(sfn_client=mock_sfn)

    result = client.start_sync_execution(
        state_machine_arn=_ARN, input_payload={"decision_id": "d1"}
    )

    assert result.output == {"state": "SUCCEEDED"}
    assert result.execution_arn == "arn:aws:states:...:execution:abc"


def test_start_sync_execution_raises_on_execution_failed_status() -> None:
    mock_sfn = MagicMock()
    mock_sfn.start_sync_execution.return_value = {
        "executionArn": "arn:aws:states:...:execution:abc",
        "status": "FAILED",
        "error": "States.TaskFailed",
        "cause": "boom",
    }
    client = StepFunctionsClient(sfn_client=mock_sfn)

    with pytest.raises(StepFunctionsExecutionFailedError):
        client.start_sync_execution(state_machine_arn=_ARN, input_payload={})


def test_start_sync_execution_maps_state_machine_does_not_exist_to_validation_error() -> None:
    mock_sfn = MagicMock()
    mock_sfn.start_sync_execution.side_effect = ClientError(
        {"Error": {"Code": "StateMachineDoesNotExist", "Message": "not found"}},
        "StartSyncExecution",
    )
    client = StepFunctionsClient(sfn_client=mock_sfn)

    with pytest.raises(ValidationError):
        client.start_sync_execution(state_machine_arn=_ARN, input_payload={})
