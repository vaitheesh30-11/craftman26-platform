"""`FaultRecord` — self-healing's own audit trail (agents phase-17 §10).

Every retry exhaustion, fallback dispatch, watchdog rescue, repair action,
and drift remediation writes one of these to DDB `SentinelFaults`
(`iam_sentinel_adapters.ddb.faults.FaultsClient`, already built against
this exact shape by backend phase-01 -- `GET /operations/faults` displays
whatever this contract's producers write). Callers hand
`FaultsClient.put()` a plain dict via `.model_dump(mode="json")`, never the
model itself, matching the adapters/agents module-boundary convention every
other contract here follows.
"""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, Field

from iam_sentinel_agents.contracts.common import Base

FaultClass = Literal[
    "transient_throttling",
    "transient_network",
    "eventual_consistency",
    "adapter_fault",
    "model_fault",
    "logic_fault",
    "infra_drift",
    "data_corruption",
    "region_outage",
]

ActionTaken = Literal["retried", "fell_back", "escalated", "auto_repaired", "paged"]


class FaultRecord(Base):
    correlation_id: str = Field(min_length=1, max_length=256)
    fault_class: FaultClass
    origin: str = Field(min_length=1, max_length=256)
    action_taken: ActionTaken
    detail: str = Field(min_length=1, max_length=2000)
    detected_at: AwareDatetime
    resolved_at: AwareDatetime | None = None


# `correlation_id` is usually a real ULID (a Prime turn's correlation id),
# but watchdog/repair/drift also mint synthetic ids for actions that have no
# in-flight turn behind them (e.g. `"f17-drift-<stack_name>"`) -- unlike
# every specialist payload contract, `FaultRecord.correlation_id` is
# deliberately not `Field(pattern=ULID_PATTERN)`.
__all__ = ["ActionTaken", "FaultClass", "FaultRecord"]
