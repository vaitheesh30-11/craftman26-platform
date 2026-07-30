"""Guardrail ID/version accessor from SSM (phase-01 §2), cached 5 minutes
in-process — matches the refresh cadence already established for budget
caps in `cost_meter.py`.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import boto3

from iam_sentinel_adapters.settings import settings

if TYPE_CHECKING:
    from mypy_boto3_ssm import SSMClient

_CACHE_TTL_SECONDS = 300.0


class GuardrailAccessor:
    def __init__(self, *, client: SSMClient | None = None) -> None:
        self._ssm: SSMClient = client or boto3.client("ssm", region_name=settings.region)
        self._cache: dict[str, tuple[str, float]] = {}

    def guardrail_id(self) -> str:
        return self._get_param(f"/sentinel/{settings.stage}/guardrail/id")

    def guardrail_version(self) -> str:
        return self._get_param(f"/sentinel/{settings.stage}/guardrail/version")

    def _get_param(self, name: str) -> str:
        now = time.monotonic()
        cached = self._cache.get(name)
        if cached is not None and now - cached[1] < _CACHE_TTL_SECONDS:
            return cached[0]

        response = self._ssm.get_parameter(Name=name)
        value = response["Parameter"]["Value"]
        self._cache[name] = (value, now)
        return value
