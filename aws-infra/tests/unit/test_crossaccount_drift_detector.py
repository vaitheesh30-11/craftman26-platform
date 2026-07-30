"""Pure-logic checks for the weekly drift-detector Lambda (phase-08 §5).
`moto` has no CloudFormation StackSet backend (same gap ADR 0008 hit for
Access Analyzer), so `cloudformation`/`cloudwatch` calls are mocked via
`unittest.mock`, matching that precedent.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_MODULE_PATH = (
    Path(__file__).resolve().parents[2] / "functions" / "crossaccount_drift_detector" / "handler.py"
)


@pytest.fixture()
def drift_handler():
    spec = importlib.util.spec_from_file_location("crossaccount_drift_detector_handler", _MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_check_stack_set_returns_drifted_instance_count(drift_handler) -> None:
    with (
        patch.object(drift_handler, "_cfn") as mock_cfn,
        patch.object(drift_handler, "time") as mock_time,
    ):
        mock_cfn.detect_stack_set_drift.return_value = {"OperationId": "op-1"}
        mock_cfn.describe_stack_set_operation.return_value = {
            "StackSetOperation": {"Status": "SUCCEEDED"}
        }
        paginator = MagicMock()
        paginator.paginate.return_value = [{"Summaries": [{"Account": "111111111111"}]}]
        mock_cfn.get_paginator.return_value = paginator

        result = drift_handler.check_stack_set("SentinelCrossAccountRole-dev")

        assert result == 1
        mock_time.sleep.assert_not_called()


def test_check_stack_set_returns_negative_one_when_detection_fails(drift_handler) -> None:
    with patch.object(drift_handler, "_cfn") as mock_cfn:
        mock_cfn.detect_stack_set_drift.return_value = {"OperationId": "op-2"}
        mock_cfn.describe_stack_set_operation.return_value = {
            "StackSetOperation": {"Status": "FAILED"}
        }

        assert drift_handler.check_stack_set("SentinelCrossAccountRole-dev") == -1


def test_handler_emits_one_metric_per_stack_set(drift_handler) -> None:
    with (
        patch.object(drift_handler, "check_stack_set", return_value=2) as mock_check,
        patch.object(drift_handler, "_cloudwatch") as mock_cloudwatch,
    ):
        result = drift_handler.handler({"stack_set_names": ["SetA", "SetB"]}, None)

        assert result == {"SetA": 2, "SetB": 2}
        assert mock_check.call_count == 2
        assert mock_cloudwatch.put_metric_data.call_count == 2
