"""Non-storage compute adapters -- currently just synchronous Lambda
invocation for backend's fast-path router bridge (backend phase-01 §5).
"""

from __future__ import annotations

from iam_sentinel_adapters.compute.lambda_client import LambdaInvocationError, LambdaInvokeClient
from iam_sentinel_adapters.compute.step_functions_client import (
    StepFunctionsClient,
    StepFunctionsExecutionFailedError,
    SyncExecutionResult,
)

__all__ = [
    "LambdaInvocationError",
    "LambdaInvokeClient",
    "StepFunctionsClient",
    "StepFunctionsExecutionFailedError",
    "SyncExecutionResult",
]
