"""Freshness contract (agents phase-10 §4 step 6): a KB retrieval older than
30 days emits an INFO metric rather than silently degrading a specialist's
confidence. Prime (Wave 3) decides how to weight a stale citation; this
module only surfaces the signal.
"""

from __future__ import annotations

from datetime import date, datetime, UTC
from typing import TYPE_CHECKING

from aws_lambda_powertools.metrics import MetricUnit

if TYPE_CHECKING:
    from aws_lambda_powertools import Metrics

_MAX_FRESH_AGE_DAYS = 30


def is_stale(retrieved_on: str, *, as_of: date | None = None) -> bool:
    reference = as_of or datetime.now(UTC).date()
    retrieved_date = date.fromisoformat(retrieved_on)
    return (reference - retrieved_date).days > _MAX_FRESH_AGE_DAYS


def emit_stale_retrieval_metric(metrics: Metrics, *, feature_id: str) -> None:
    metrics.add_dimension(name="feature_id", value=feature_id)
    metrics.add_metric(name="SentinelKbStaleRetrieval", unit=MetricUnit.Count, value=1)
