"""Cost-guardrail contracts (agents-phase-16 §4, docs/decisions/0033).

`SpendSample`/`BudgetSnapshot`/`CircuitBreakerState` match the phase-16 spec's
interface contracts verbatim. They are the agents-module *reporting* view
over adapters' `CostMeter`/`BreakerAccessor` DDB rows -- `budget_gate`
builds them from `CostMeter.samples()`/`BreakerAccessor.state()` rather than
either adapter returning a Pydantic model itself (adapters/ has no
dependency on agents/'s contract package, and never should -- the opposite
direction is the one exception this repo allows, per agents phase-10,
docs/decisions/0010).
"""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, Field

from iam_sentinel_agents.contracts.common import Base

SpendSampleKind = Literal[
    "bedrock_input_tokens",
    "bedrock_output_tokens",
    "bedrock_dollars",
    "athena_bytes_scanned",
    "athena_dollars",
    "lambda_milliseconds",
    "tool_invocations",
]

BudgetMode = Literal["fast", "slow_single", "slow_multi", "shadow"]
BreakerName = Literal["bedrock", "athena", "platform"]
BreakerState = Literal["closed", "half_open", "open"]


class SpendSample(Base):
    correlation_id: str = Field(min_length=1)
    kind: SpendSampleKind
    amount: float = Field(ge=0.0)
    at: AwareDatetime
    feature_id: str = "unknown"
    principal: str = "unknown"
    mode: BudgetMode = "fast"


class BudgetSnapshot(Base):
    correlation_id: str = Field(min_length=1)
    started_at: AwareDatetime
    samples: list[SpendSample] = Field(default_factory=list)
    caps: dict[str, float] = Field(default_factory=dict)
    breached_cap: str | None = None
    projected_dollars: float = Field(default=0.0, ge=0.0)


class CircuitBreakerState(Base):
    breaker_name: BreakerName
    state: BreakerState
    opened_at: AwareDatetime | None = None
    open_reason: str | None = None
    next_probe_at: AwareDatetime | None = None


class WeeklyCostReport(Base):
    """Weekly cost-attribution rollup (phase-16 §5 step 7 / §2)."""

    week_id: str = Field(pattern=r"^\d{4}-W\d{2}$")
    top_principals: list[dict[str, float | str]] = Field(default_factory=list, max_length=10)
    cost_per_feature: dict[str, float] = Field(default_factory=dict)
    cost_per_finding: dict[str, float] = Field(default_factory=dict)
    fast_slow_split: dict[str, float] = Field(default_factory=dict)
    shadow_overhead_dollars: float = Field(default=0.0, ge=0.0)
    generated_at: AwareDatetime
