"""Weekly drift check for the two cross-account StackSets (phase-08 §5).

`DetectStackSetDrift` is asynchronous -- it returns an OperationId and the
actual per-instance drift status only shows up later via
`DescribeStackSetOperation` / `ListStackInstances`. This handler starts
detection for every StackSet it's told about, polls
`DescribeStackSetOperation` with a bounded backoff (Lambda itself is the
timeout backstop -- see `crossaccount_stack.py`'s `timeout=Duration.minutes(10)`),
then counts instances left in a DRIFTED state and emits one CloudWatch
metric per StackSet so `crossaccount_stack.py`'s alarm can fire on it.
"""

from __future__ import annotations

import time
from typing import Any

import boto3

_cfn = boto3.client("cloudformation")
_cloudwatch = boto3.client("cloudwatch")

_METRIC_NAMESPACE = "IAMSentinel/CrossAccount"
_METRIC_NAME = "SentinelCrossAccountDrift"
_POLL_INTERVAL_SECONDS = 15
_MAX_POLLS = 32  # ~8 minutes, inside the Lambda's 10-minute timeout.


def _wait_for_operation(stack_set_name: str, operation_id: str) -> str:
    for _ in range(_MAX_POLLS):
        response = _cfn.describe_stack_set_operation(
            StackSetName=stack_set_name, OperationId=operation_id
        )
        status = response["StackSetOperation"]["Status"]
        if status not in ("RUNNING", "QUEUED"):
            return str(status)
        time.sleep(_POLL_INTERVAL_SECONDS)
    return "TIMED_OUT"


def _count_drifted_instances(stack_set_name: str) -> int:
    paginator = _cfn.get_paginator("list_stack_instances")
    drifted = 0
    for page in paginator.paginate(
        StackSetName=stack_set_name, Filters=[{"Name": "DRIFT_STATUS", "Values": "DRIFTED"}]
    ):
        drifted += len(page["Summaries"])
    return drifted


def check_stack_set(stack_set_name: str) -> int:
    """Runs detection end-to-end for one StackSet. Returns the drifted-instance
    count so `handler` can emit it and the unit tests can assert on pure
    return values instead of mocking CloudWatch."""
    started = _cfn.detect_stack_set_drift(StackSetName=stack_set_name)
    operation_status = _wait_for_operation(stack_set_name, started["OperationId"])
    if operation_status != "SUCCEEDED":
        # A failed/timed-out detection run is itself signal -- surface it as
        # drift rather than silently reporting zero.
        return -1
    return _count_drifted_instances(stack_set_name)


def handler(event: dict[str, Any], _context: object) -> dict[str, int]:
    results: dict[str, int] = {}
    for stack_set_name in event["stack_set_names"]:
        drifted = check_stack_set(stack_set_name)
        results[stack_set_name] = drifted
        _cloudwatch.put_metric_data(
            Namespace=_METRIC_NAMESPACE,
            MetricData=[
                {
                    "MetricName": _METRIC_NAME,
                    "Dimensions": [{"Name": "StackSetName", "Value": stack_set_name}],
                    "Value": float(max(drifted, 0)),
                    "Unit": "Count",
                }
            ],
        )
    return results
