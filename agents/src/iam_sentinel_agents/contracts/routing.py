"""`RoutingDecision`/`DivergenceRecord` — agents phase-15 §5 Interface
Contracts. `DivergenceRecord` deliberately carries a `feature_id` field
(`adapters.ddb.divergence.DivergenceClient`'s own docstring flags this as
the gap its `feature-divergence-index` GSI needs a producer to fill --
this is that producer) even though the spec's own §5 code block omits it;
the GSI is real (aws-infra phase-02) and unusable without it, and adding an
extra required field to a phase-15-owned contract that phase-15 itself is
first to populate carries no drift risk against another consumer.
"""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, Field

from iam_sentinel_agents.contracts.common import Base, FeatureID

RoutingMode = Literal["fast", "slow", "shadow"]
DivergenceKind = Literal["identical", "semantic_match", "material_disagreement"]


class RoutingDecision(Base):
    mode: RoutingMode
    reason: str = Field(min_length=1, max_length=512)
    dispatch_target: str = Field(min_length=1, max_length=64)
    matched_policy_rule_id: str | None = None
    fallback_target: str | None = None
    correlation_id: str = Field(min_length=1, max_length=128)


class DivergenceRecord(Base):
    correlation_id: str = Field(min_length=1, max_length=128)
    feature_id: FeatureID
    input_hash: str = Field(min_length=1, max_length=128)
    fast_output: dict[str, object]
    slow_output: dict[str, object]
    divergence_kind: DivergenceKind
    diff_summary: str = Field(max_length=4096)
    reviewed: bool = False
    detected_at: AwareDatetime
