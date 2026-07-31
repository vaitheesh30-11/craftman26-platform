"""`GET /operations/*` read models (backend phase-01 §7). `FaultRecord`'s
canonical contract lives in `agents/docs/phase-17-self-healing.txt §10`
(self-healing, not yet built) -- kept loosely typed here for the same
reason `schemas/decision.py` keeps nested verdicts loose: this phase only
displays records some future producer writes, per that phase doc's own
contract.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from iam_sentinel_backend.schemas.common import ResponseBase

BreakerState = Literal["closed", "half_open", "open"]
DivergenceKind = Literal["identical", "semantic_match", "material_disagreement"]

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


class FaultRecordOut(ResponseBase):
    correlation_id: str
    fault_class: FaultClass
    origin: str
    action_taken: Literal["retried", "fell_back", "escalated", "auto_repaired", "paged"]
    detail: str
    detected_at: str
    resolved_at: str | None = None


class FaultsPage(ResponseBase):
    items: list[FaultRecordOut]
    next_token: str | None = None


class CostReportOut(ResponseBase):
    """Passthrough wrapper for `SentinelReports/cost/{year}-W{week}.json`
    (`agents/docs/phase-16-cost-guardrails.txt §5`, not yet built) -- the
    report body's internal shape is that phase's contract to define; this
    endpoint's job is only "return the latest one, or 404".
    """

    report_key: str
    body: dict[str, object] = Field(default_factory=dict)


class DivergenceRecordOut(ResponseBase):
    """Mirrors `DivergenceRecord` (`agents/docs/phase-15-dual-mode-execution.
    txt §5`, not yet built -- see `adapters/ddb/divergence.py`'s module
    docstring). `feature_id` isn't part of that Pydantic contract but is
    the GSI partition key `DivergenceClient.list_recent` queries on, so it's
    modeled here as optional rather than assumed absent.
    """

    correlation_id: str
    feature_id: str | None = None
    input_hash: str
    divergence_kind: DivergenceKind
    diff_summary: str
    reviewed: bool = False
    detected_at: str


class DivergencePage(ResponseBase):
    items: list[DivergenceRecordOut]
    next_token: str | None = None


class BreakerStateOut(ResponseBase):
    breaker_name: str
    state: BreakerState


class DlqDepthOut(ResponseBase):
    queue_url: str
    approximate_messages: int


class HealthSnapshotOut(ResponseBase):
    """Composite health snapshot (backend phase-04 §2/§4 step 2) -- which
    breakers/DLQs count as "every known" one is settings-driven, not
    discovered; see `AdapterSettings.known_breaker_names`/`dlq_queue_urls`
    and ADR 0023.
    """

    breakers: list[BreakerStateOut]
    dlqs: list[DlqDepthOut]
