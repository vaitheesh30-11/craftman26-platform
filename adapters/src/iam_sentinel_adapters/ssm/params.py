"""Cached `ssm:GetParameter` reads (backend phase-03 §3 step 3) -- the
`SentinelApprovalApply` state machine's ARN is resolved from
`/sentinel/{stage}/approval/state-machine-arn` rather than hardcoded or
injected as a required env var, so `aws-infra` can publish that parameter
once the state machine is actually built (it is not yet -- see
`docs/decisions` for backend phase-03's scope note) without backend needing
a redeploy.

`get_parameter` returns `None` on `ParameterNotFound` rather than raising --
callers decide how to degrade (the same "clear error code, not a crash"
precedent ADR 0017's `BACKEND_NOT_PACKAGED` shim set for an unbuilt callee).
This adapter never fails a whole request just because a parameter hasn't
been published yet; it only ever reflects what SSM actually holds.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import boto3

from iam_sentinel_adapters.settings import settings

if TYPE_CHECKING:
    from mypy_boto3_ssm import SSMClient

_CACHE_TTL_SECONDS = 300.0


class SsmParameterClient:
    def __init__(self, *, ssm_client: SSMClient | None = None) -> None:
        self._ssm: SSMClient = ssm_client or boto3.client("ssm", region_name=settings.region)
        self._cache: dict[str, tuple[str, float]] = {}

    def get_parameter(self, name: str) -> str | None:
        cached = self._cache.get(name)
        now = time.monotonic()
        if cached is not None and now - cached[1] < _CACHE_TTL_SECONDS:
            return cached[0]

        try:
            response = self._ssm.get_parameter(Name=name)
        except self._ssm.exceptions.ParameterNotFound:
            return None

        value = str(response["Parameter"]["Value"])
        self._cache[name] = (value, now)
        return value
