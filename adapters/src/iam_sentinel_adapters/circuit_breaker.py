"""DDB-backed circuit breaker state accessor.

Transitions (phase-00 §6): 3 failures within 60 seconds trips a breaker to
`open` for a 5-minute cooldown; the first call after cooldown gets exactly
one `half_open` probe; success closes it, failure reopens for another
5 minutes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal

import boto3

from iam_sentinel_adapters.errors import CircuitOpenError
from iam_sentinel_adapters.settings import settings

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

BreakerState = Literal["closed", "half_open", "open"]

_FAILURE_THRESHOLD = 3
_FAILURE_WINDOW = timedelta(seconds=60)
_OPEN_COOLDOWN = timedelta(minutes=5)


class BreakerAccessor:
    def __init__(self, *, table: Table | None = None) -> None:
        self._table: Table = table or boto3.resource(
            "dynamodb", region_name=settings.region
        ).Table(settings.breakers_table)

    def state(self, breaker_name: str) -> BreakerState:
        item = self._get(breaker_name)
        if item is None:
            return "closed"

        state: BreakerState = item["state"]
        if state == "open" and self._cooldown_elapsed(item):
            self._write(breaker_name, "half_open", failure_count=0)
            return "half_open"
        return state

    def record_success(self, breaker_name: str) -> None:
        self._write(breaker_name, "closed", failure_count=0)

    def record_failure(self, breaker_name: str) -> None:
        item = self._get(breaker_name)

        if item is not None and item["state"] == "half_open":
            self.trip(breaker_name, "probe failed")
            return

        failure_count = 1
        if item is not None and item["state"] == "closed":
            last_failure_at = datetime.fromisoformat(item["last_failure_at"])
            if datetime.now(UTC) - last_failure_at <= _FAILURE_WINDOW:
                failure_count = int(item["failure_count"]) + 1

        if failure_count >= _FAILURE_THRESHOLD:
            self.trip(breaker_name, f"{failure_count} failures within {_FAILURE_WINDOW.seconds}s")
            return

        self._write(breaker_name, "closed", failure_count=failure_count)

    def trip(self, breaker_name: str, reason: str) -> None:
        now = datetime.now(UTC)
        self._table.put_item(
            Item={
                "breaker_name": breaker_name,
                "state": "open",
                "failure_count": _FAILURE_THRESHOLD,
                "last_failure_at": now.isoformat(),
                "opened_at": now.isoformat(),
                "reason": reason,
            }
        )

    def raise_if_open(self, breaker_name: str) -> None:
        if self.state(breaker_name) == "open":
            raise CircuitOpenError(f"breaker {breaker_name!r} is open")

    def _get(self, breaker_name: str) -> dict[str, Any] | None:
        response = self._table.get_item(Key={"breaker_name": breaker_name})
        return response.get("Item")

    def _write(self, breaker_name: str, state: BreakerState, *, failure_count: int) -> None:
        self._table.put_item(
            Item={
                "breaker_name": breaker_name,
                "state": state,
                "failure_count": failure_count,
                "last_failure_at": datetime.now(UTC).isoformat(),
            }
        )

    def _cooldown_elapsed(self, item: dict[str, Any]) -> bool:
        opened_at = datetime.fromisoformat(item["opened_at"])
        return datetime.now(UTC) - opened_at >= _OPEN_COOLDOWN
