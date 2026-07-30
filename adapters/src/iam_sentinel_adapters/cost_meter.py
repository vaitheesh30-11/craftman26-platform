"""EMF cost-metering and DDB spend-sample ledger.

The EMF metric emitted in `record` is the authoritative real-time signal;
the DDB write is best-effort and only backs `projected()`'s cross-process
aggregation (phase-00 §5, risk table). Budget caps live in SSM under
`/sentinel/budget/<kind>` and are cached in-process for 5 minutes.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from enum import Enum
from threading import Lock
from typing import TYPE_CHECKING

import boto3
from aws_lambda_powertools import Metrics
from aws_lambda_powertools.metrics import MetricUnit

from iam_sentinel_adapters.errors import BudgetExceededError
from iam_sentinel_adapters.settings import settings

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table
    from mypy_boto3_ssm import SSMClient

_PROJECTION_CACHE_TTL_SECONDS = 5.0
_BUDGET_CACHE_TTL_SECONDS = 300.0


class SpendKind(str, Enum):
    BEDROCK_TOKENS = "bedrock_tokens"
    BEDROCK_AGENT_INVOCATION = "bedrock_agent_invocation"
    ATHENA_SCAN_BYTES = "athena_scan_bytes"
    LAMBDA_DURATION = "lambda_duration"
    ZELKOVA_INVOCATION = "zelkova_invocation"


class CostMeter:
    def __init__(
        self,
        *,
        table: Table | None = None,
        ssm_client: SSMClient | None = None,
        metrics: Metrics | None = None,
    ) -> None:
        self._table: Table = table or boto3.resource(
            "dynamodb", region_name=settings.region
        ).Table(settings.budget_table)
        self._ssm: SSMClient = ssm_client or boto3.client("ssm", region_name=settings.region)
        self._metrics = metrics or Metrics(namespace=settings.metric_namespace)
        self._lock = Lock()
        self._projection_cache: dict[str, tuple[float, float]] = {}
        self._budget_cache: dict[SpendKind, tuple[float, float]] = {}

    def record(
        self,
        correlation_id: str,
        kind: SpendKind,
        amount: float,
        *,
        feature_id: str = "unknown",
        principal: str = "unknown",
        mode: str = "unknown",
    ) -> None:
        self._metrics.add_dimension(name="feature_id", value=feature_id)
        self._metrics.add_dimension(name="principal", value=principal)
        self._metrics.add_dimension(name="mode", value=mode)
        self._metrics.add_metric(name=f"SentinelSpend{kind.value}", unit=MetricUnit.Count, value=amount)

        with self._lock:
            self._table.put_item(
                Item={
                    "correlation_id": correlation_id,
                    "sample_id": f"{int(time.time() * 1000)}-{uuid.uuid4().hex}",
                    "kind": kind.value,
                    "amount": str(amount),
                    "recorded_at": datetime.now(UTC).isoformat(),
                }
            )
            self._projection_cache.pop(correlation_id, None)

    def projected(self, correlation_id: str) -> float:
        now = time.monotonic()
        cached = self._projection_cache.get(correlation_id)
        if cached is not None and now - cached[1] < _PROJECTION_CACHE_TTL_SECONDS:
            return cached[0]

        response = self._table.query(
            KeyConditionExpression="correlation_id = :cid",
            ExpressionAttributeValues={":cid": correlation_id},
        )
        total = 0.0
        for item in response.get("Items", []):
            total += float(str(item["amount"]))
        self._projection_cache[correlation_id] = (total, now)
        return total

    def check_budget(self, correlation_id: str, kind: SpendKind, delta: float) -> None:
        cap = self._budget_cap(kind)
        projected = self.projected(correlation_id) + delta
        if projected > cap:
            raise BudgetExceededError(
                f"{kind.value} would push correlation {correlation_id!r} to "
                f"{projected}, cap is {cap}"
            )

    def _budget_cap(self, kind: SpendKind) -> float:
        now = time.monotonic()
        cached = self._budget_cache.get(kind)
        if cached is not None and now - cached[1] < _BUDGET_CACHE_TTL_SECONDS:
            return cached[0]

        parameter = self._ssm.get_parameter(Name=f"/sentinel/budget/{kind.value}")
        cap = float(parameter["Parameter"]["Value"])
        self._budget_cache[kind] = (cap, now)
        return cap
