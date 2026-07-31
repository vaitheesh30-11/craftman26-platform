"""Fault-taxonomy-aware retry (agents phase-17 §3, §4).

`iam_sentinel_adapters.retry` already implements the four backoff shapes
this phase's spec names verbatim (`Policy.AGGRESSIVE/CAUTIOUS/SINGLE/NONE`,
each with a hard attempt cap AND a hard total-time cap -- backend phase-00
§4 built that ahead of this phase, for adapters' own internal callers).
This module does not reimplement backoff; it wraps that existing primitive
with the piece phase-17 actually adds: classifying a failure against
§3's fault taxonomy, picking the §4-assigned policy for it, and writing a
`FaultRecord` to `SentinelFaults` for every non-transient fault (and a
1-in-100 sample of `transient_throttling`, per §14's noise mitigation)
so `GET /operations/faults` can show it.
"""

from __future__ import annotations

import random
from datetime import datetime, UTC
from functools import wraps
from typing import ParamSpec, TYPE_CHECKING, TypeVar

from iam_sentinel_adapters.ddb.faults import FaultsClient
from iam_sentinel_adapters.errors import SentinelAdapterError, TransientError
from iam_sentinel_adapters.retry import Policy
from iam_sentinel_adapters.retry import retry as _adapter_retry

from iam_sentinel_agents.contracts.fault import ActionTaken, FaultClass, FaultRecord

if TYPE_CHECKING:
    from collections.abc import Callable

P = ParamSpec("P")
T = TypeVar("T")

# §14 risk mitigation: "sampled writes for transient_throttling (1/100);
# every non-transient fault written 100%."
_TRANSIENT_THROTTLING_SAMPLE_RATE = 0.01

# §4 "Assignments" -- adapter call site -> (retry policy, taxonomy class).
# Callers look their own call site up here rather than hardcoding a policy
# inline, so the assignment table lives in exactly one place and can't
# silently drift between what §4's prose says and what the code does.
ADAPTER_CALL_SITE_POLICY: dict[str, tuple[Policy, FaultClass]] = {
    "bedrock_invoke_throttling": (Policy.AGGRESSIVE, "transient_throttling"),
    "bedrock_invoke_validation": (Policy.NONE, "model_fault"),
    "bedrock_invoke_access_denied": (Policy.NONE, "model_fault"),
    "bedrock_invoke_guardrail": (Policy.NONE, "model_fault"),
    "zelkova_check_no_new_access_throttling": (Policy.CAUTIOUS, "adapter_fault"),
    "zelkova_check_no_new_access_validation": (Policy.NONE, "logic_fault"),
    "sts_assume_role_throttling": (Policy.AGGRESSIVE, "transient_throttling"),
    "sts_assume_role_access_denied": (Policy.NONE, "adapter_fault"),
    "ddb_put_update_throttling": (Policy.AGGRESSIVE, "transient_throttling"),
    "ddb_put_update_provisioned_exceeded": (Policy.SINGLE, "transient_throttling"),
    "athena_start_query_too_many_requests": (Policy.CAUTIOUS, "transient_throttling"),
    "athena_start_query_invalid_request": (Policy.NONE, "logic_fault"),
    "iam_put_role_policy": (Policy.SINGLE, "adapter_fault"),
}


class RetryExhausted(SentinelAdapterError):  # noqa: N818 -- exact name §14 risk 1 specifies
    """Raised once a self-healing retry policy's attempt/time budget is
    spent (§14 risk 1: "every retry decorator has a hard iteration cap (5)
    and a total-time cap (30s); breach raises `RetryExhausted`" -- the caps
    themselves are `Policy`'s, this is the taxonomy-aware exception type
    callers actually catch).
    """

    def __init__(self, fault_class: FaultClass, attempts: int, *, cause: Exception) -> None:
        super().__init__(f"{fault_class}: exhausted after {attempts} attempt(s): {cause}")
        self.fault_class = fault_class
        self.attempts = attempts
        self.__cause__ = cause


def should_sample(fault_class: FaultClass, *, rng: Callable[[], float] = random.random) -> bool:
    """§14: only `transient_throttling` is sampled; every other class is
    always written."""
    if fault_class == "transient_throttling":
        return rng() < _TRANSIENT_THROTTLING_SAMPLE_RATE
    return True


def record_fault(
    *,
    correlation_id: str,
    fault_class: FaultClass,
    origin: str,
    action_taken: ActionTaken,
    detail: str,
    resolved_at: datetime | None = None,
    faults_client: FaultsClient | None = None,
    force_write: bool = False,
    rng: Callable[[], float] = random.random,
) -> FaultRecord | None:
    """Writes a `FaultRecord` to `SentinelFaults`, honoring §14's sampling
    rule unless `force_write` overrides it (used for the terminal
    `escalated`/`auto_repaired`/`paged` outcomes, which are never sampled
    regardless of fault class -- only the noisy "retried and succeeded"
    outcome for `transient_throttling` is sampled). Returns `None` when
    sampling drops the write, so callers can assert on that in tests.
    """
    if not force_write and not should_sample(fault_class, rng=rng):
        return None
    record = FaultRecord(
        correlation_id=correlation_id,
        fault_class=fault_class,
        origin=origin,
        action_taken=action_taken,
        detail=detail[:2000],
        detected_at=datetime.now(UTC),
        resolved_at=resolved_at,
    )
    (faults_client or FaultsClient()).put(record.model_dump(mode="json"))
    return record


def with_fault_recording(
    *,
    policy: Policy,
    fault_class: FaultClass,
    origin: str,
    retry_on: tuple[type[Exception], ...] = (TransientError,),
    correlation_id_of: Callable[..., str] = lambda *a, **kw: str(  # noqa: ARG005
        kw.get("correlation_id", "unknown")
    ),
    faults_client: FaultsClient | None = None,
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """Decorator composing `iam_sentinel_adapters.retry.retry` (the actual
    backoff/cap mechanics) with `record_fault` (this phase's addition):
    on final exhaustion, writes an `escalated` `FaultRecord` and raises
    `RetryExhausted`; on a retried-then-succeeded call, writes a sampled
    `retried` `FaultRecord`. A call that never needed a retry writes
    nothing -- the common, uninteresting case.
    """

    def decorator(fn: Callable[P, T]) -> Callable[P, T]:
        # Not thread-safe by design: each Lambda invocation is single-
        # threaded per phase-00 §3.3's execution model, and this counter's
        # lifetime is scoped to one `inner()` call (reset at its start),
        # never shared across concurrent invocations of the same warm
        # container -- Python's GIL serializes the increment either way.
        attempts_counter = {"count": 0}

        def counted(*args: P.args, **kwargs: P.kwargs) -> T:
            attempts_counter["count"] += 1
            return fn(*args, **kwargs)

        wrapped = _adapter_retry(policy=policy, retry_on=retry_on)(counted)

        @wraps(fn)
        def inner(*args: P.args, **kwargs: P.kwargs) -> T:
            attempts_counter["count"] = 0
            correlation_id = correlation_id_of(*args, **kwargs)
            try:
                result = wrapped(*args, **kwargs)
            except retry_on as exc:
                attempts = attempts_counter["count"]
                record_fault(
                    correlation_id=correlation_id,
                    fault_class=fault_class,
                    origin=origin,
                    action_taken="escalated",
                    detail=str(exc),
                    faults_client=faults_client,
                    force_write=True,
                )
                raise RetryExhausted(fault_class, attempts, cause=exc) from exc
            attempts = attempts_counter["count"]
            if attempts > 1:
                record_fault(
                    correlation_id=correlation_id,
                    fault_class=fault_class,
                    origin=origin,
                    action_taken="retried",
                    detail=f"succeeded after {attempts} attempt(s)",
                    faults_client=faults_client,
                )
            return result

        return inner

    return decorator
