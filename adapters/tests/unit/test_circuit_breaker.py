from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from iam_sentinel_adapters.circuit_breaker import BreakerAccessor
from iam_sentinel_adapters.errors import CircuitOpenError

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table


def test_closed_by_default(breakers_table: Table) -> None:
    accessor = BreakerAccessor(table=breakers_table)
    assert accessor.state("bedrock-invoke") == "closed"


def test_three_failures_trip_the_breaker(breakers_table: Table) -> None:
    accessor = BreakerAccessor(table=breakers_table)
    for _ in range(3):
        accessor.record_failure("bedrock-invoke")

    assert accessor.state("bedrock-invoke") == "open"
    with pytest.raises(CircuitOpenError):
        accessor.raise_if_open("bedrock-invoke")


def test_success_closes_an_open_breaker(breakers_table: Table) -> None:
    accessor = BreakerAccessor(table=breakers_table)
    accessor.trip("bedrock-invoke", reason="manual")
    accessor.record_success("bedrock-invoke")

    assert accessor.state("bedrock-invoke") == "closed"


def test_failed_probe_reopens_the_breaker(breakers_table: Table) -> None:
    accessor = BreakerAccessor(table=breakers_table)
    accessor.trip("bedrock-invoke", reason="manual")
    accessor._write("bedrock-invoke", "half_open", failure_count=0)

    accessor.record_failure("bedrock-invoke")

    assert accessor.state("bedrock-invoke") == "open"
