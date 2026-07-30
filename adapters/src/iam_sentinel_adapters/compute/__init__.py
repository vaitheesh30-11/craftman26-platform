"""Non-storage compute adapters -- currently just synchronous Lambda
invocation for backend's fast-path router bridge (backend phase-01 §5).
"""

from __future__ import annotations

from iam_sentinel_adapters.compute.lambda_client import LambdaInvocationError, LambdaInvokeClient

__all__ = ["LambdaInvocationError", "LambdaInvokeClient"]
