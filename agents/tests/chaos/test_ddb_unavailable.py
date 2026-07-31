"""Chaos: DDB unavailable (phase-13 §4 Step 4). Real `IdempotencyClient`/
`DynamoDbHelper` retry wrapping against a fake table whose `put_item`
always raises `ProvisionedThroughputExceededException`. Passes when: the
write is retried per `Policy.AGGRESSIVE` (6 attempts) and the failure then
propagates as `ThrottlingError` -- `PrimePostTurnProcessor.process` must
never write a partial `DecisionRecord`/evidence blob when the very first
step (claiming idempotency) cannot complete.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from iam_sentinel_adapters.ddb.idempotency import IdempotencyClient
from iam_sentinel_adapters.errors import ThrottlingError

from iam_sentinel_agents.prime.post_turn import PrimePostTurnProcessor
from tests.contract._factories import make_query, make_verdict


class _FakeThroughputError(Exception):
    pass


class _FakeConditionalCheckFailedError(Exception):
    pass


def _always_throttled_table() -> MagicMock:
    table = MagicMock()
    table.meta.client.exceptions.ConditionalCheckFailedException = _FakeConditionalCheckFailedError
    table.meta.client.exceptions.ProvisionedThroughputExceededException = _FakeThroughputError
    table.put_item.side_effect = _FakeThroughputError("throughput exceeded")
    return table


def test_idempotency_claim_retries_then_raises_throttling_error() -> None:
    table = _always_throttled_table()
    client = IdempotencyClient(table=table, breaker=MagicMock())

    with pytest.raises(ThrottlingError):
        client.claim("01JBP2VHF9K3Q0Z8R7X6M5N4C6")

    assert table.put_item.call_count == 6


def test_post_turn_process_never_writes_a_partial_decision_when_idempotency_is_unavailable() -> None:
    idempotency = MagicMock()
    idempotency.claim.side_effect = ThrottlingError("SentinelIdempotency-dev unavailable")
    decisions = MagicMock()
    evidence = MagicMock()
    security_hub = MagicMock()
    sns = MagicMock()
    processor = PrimePostTurnProcessor(
        idempotency=idempotency,
        decisions=decisions,
        evidence=evidence,
        security_hub=security_hub,
        sns=sns,
    )

    with pytest.raises(ThrottlingError):
        processor.process(query=make_query(), verdicts=[make_verdict()], narrative="n/a")

    decisions.put.assert_not_called()
    evidence.put_signed_evidence.assert_not_called()
    sns.publish_critical_finding.assert_not_called()
    security_hub.import_findings.assert_not_called()
