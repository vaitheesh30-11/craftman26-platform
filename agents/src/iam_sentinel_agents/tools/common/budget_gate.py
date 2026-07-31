"""Pre-invocation budget gate (agents-phase-16 §5 steps 2 and 5,
docs/decisions/0032).

`check_startable` is the one call `PrimeSupervisor.ask` makes before every
`invoke_agent` -- it enforces the two budget layers phase-01's mid-
invocation `BedrockProvider`/`GrokProvider` gate (phase-16 §5 step 3,
already built in adapters phase-01) does *not* cover:

- the per-principal-per-day dollar cap (phase-16 §3.2), and
- the two circuit breakers (`bedrock`, `athena`) a correlation must clear
  before it is even allowed to start (phase-16 §5 step 5).

Per-correlation dollar/token caps and the mid-invocation Bedrock gate are
already enforced inside `BedrockProvider`/`GrokProvider` (adapters
phase-01 §4 step 3) -- this module does not duplicate that check, it adds
the two layers phase-01 had no reason to know about yet.

Daily-principal accounting reuses `CostMeter`'s existing `correlation_id`
partition key rather than adding a new DDB table or GSI: the "correlation
id" for a daily-cap sample is the synthetic key `daily#<principal>#<date>`
(`daily_principal_key`). This is a deliberate, documented reuse (not a
schema migration) -- see docs/decisions/0032 for why a new `SentinelBudget`
GSI was scoped out of this phase.
"""

from __future__ import annotations

from datetime import date, datetime, UTC
from typing import Literal, TYPE_CHECKING

from iam_sentinel_adapters.cost_meter import SpendKind
from iam_sentinel_adapters.errors import BudgetExceededError, CircuitOpenError
from iam_sentinel_adapters.settings import settings as adapter_settings

if TYPE_CHECKING:
    from iam_sentinel_adapters.circuit_breaker import BreakerAccessor
    from iam_sentinel_adapters.cost_meter import CostMeter

InvocationMode = Literal["fast", "slow_single", "slow_multi"]

_ESTIMATED_COST_BY_MODE: dict[InvocationMode, float] = {
    "fast": adapter_settings.estimated_cost_fast,
    "slow_single": adapter_settings.estimated_cost_slow_single,
    "slow_multi": adapter_settings.estimated_cost_slow_multi,
}

_STARTUP_BREAKERS = ("bedrock", "athena")


def estimate_cost(mode: InvocationMode) -> float:
    """Pre-invocation cost heuristic (phase-16 §5 step 2)."""
    return _ESTIMATED_COST_BY_MODE[mode]


def daily_principal_key(principal: str, day: date | None = None) -> str:
    resolved_day = day or datetime.now(UTC).date()
    return f"daily#{principal}#{resolved_day.isoformat()}"


def check_startable(
    *,
    correlation_id: str,
    principal: str,
    mode: InvocationMode,
    cost_meter: CostMeter,
    breaker: BreakerAccessor,
    day: date | None = None,
) -> None:
    """Raises `CircuitOpenError` or `BudgetExceededError` (never both --
    the breaker check runs first since a tripped breaker means every
    downstream cost signal is already suspect) if this correlation should
    not be allowed to start. Callers (`PrimeSupervisor.ask`, specialist
    entry points) catch both and answer `verdict=INCONCLUSIVE` per phase-16
    §5 step 3's "Prime and specialists catch `BudgetExceededError`" rule,
    which this module extends to `CircuitOpenError` for the same reason.
    """
    for breaker_name in _STARTUP_BREAKERS:
        breaker.raise_if_open(breaker_name)

    estimated = estimate_cost(mode)
    daily_key = daily_principal_key(principal, day)
    cost_meter.check_budget(daily_key, SpendKind.PRINCIPAL_DAILY_DOLLARS, estimated)
    cost_meter.check_budget(correlation_id, SpendKind.BEDROCK_DOLLARS, estimated)


def record_startup_spend(
    *,
    correlation_id: str,
    principal: str,
    mode: InvocationMode,
    cost_meter: CostMeter,
    feature_id: str = "PRIME",
    day: date | None = None,
) -> None:
    """Records the estimated cost against both the per-correlation and
    per-principal-daily ledgers once `check_startable` has cleared a
    request -- mirrors `check_startable`'s two-key write so the next
    request's `projected()` reflects this one immediately, not after the
    real Bedrock usage sample lands.
    """
    estimated = estimate_cost(mode)
    daily_key = daily_principal_key(principal, day)
    cost_meter.record(
        correlation_id,
        SpendKind.BEDROCK_DOLLARS,
        estimated,
        feature_id=feature_id,
        principal=principal,
        mode=mode,
    )
    cost_meter.record(
        daily_key,
        SpendKind.PRINCIPAL_DAILY_DOLLARS,
        estimated,
        feature_id=feature_id,
        principal=principal,
        mode=mode,
    )


def check_tool_invocation_cap(*, correlation_id: str, cost_meter: CostMeter) -> None:
    """Runaway-agent guard (phase-16 §3.1, §8 acceptance criterion: "an
    agent tries to make 100 Bedrock calls; halted at cap 30"). Callers
    invoke this once per action-group tool call, before recording the
    invocation itself.
    """
    cost_meter.check_budget(correlation_id, SpendKind.TOOL_INVOCATIONS, 1.0)


def record_tool_invocation(*, correlation_id: str, cost_meter: CostMeter) -> None:
    cost_meter.record(correlation_id, SpendKind.TOOL_INVOCATIONS, 1.0)


__all__ = [
    "BudgetExceededError",
    "CircuitOpenError",
    "InvocationMode",
    "check_startable",
    "check_tool_invocation_cap",
    "daily_principal_key",
    "estimate_cost",
    "record_startup_spend",
    "record_tool_invocation",
]
