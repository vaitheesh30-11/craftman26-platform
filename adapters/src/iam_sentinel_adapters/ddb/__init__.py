"""Typed, retry-guarded DynamoDB helpers (phase-05). Only a representative
subset of the 14-table inventory is implemented here — see ADR 0006.
"""

from __future__ import annotations

from iam_sentinel_adapters.ddb.base import DynamoDbHelper
from iam_sentinel_adapters.ddb.decisions import DecisionsClient
from iam_sentinel_adapters.ddb.decisions_in_flight import DecisionsInFlightClient
from iam_sentinel_adapters.ddb.findings import FindingsClient
from iam_sentinel_adapters.ddb.idempotency import IdempotencyClient

__all__ = [
    "DecisionsClient",
    "DecisionsInFlightClient",
    "DynamoDbHelper",
    "FindingsClient",
    "IdempotencyClient",
]
