"""Per-specialist fallback dispatcher (agents phase-17 §5).

"When a specialist's slow-path invocation fails, the router tries a
fallback per §4 of phase-15 (dual-mode) -- the fast path deterministic
mirror. When both paths fail, the specialist emits `verdict=ESCALATE`."
`agents/docs/phase-15-dual-mode-execution.txt`'s `router.execute(mode=...)`
is this dispatcher's intended caller once that phase lands (sprint step
40, a sibling in-flight branch as of this writing -- not yet on `main`);
`dispatch_with_fallback` is written against that documented contract
(slow path / fast path as two zero-arg callables) rather than importing
anything from phase-15 directly, the same "build against the documented
contract, not the not-yet-landed implementation" precedent ADR 0018 used
for `RouterBridgeService`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, ParamSpec, TYPE_CHECKING, TypeVar

from iam_sentinel_agents.errors import SentinelAgentError
from iam_sentinel_agents.tools.common.retry import record_fault

if TYPE_CHECKING:
    from collections.abc import Callable

    from iam_sentinel_adapters.ddb.faults import FaultsClient

    from iam_sentinel_agents.contracts.common import FeatureID

P = ParamSpec("P")
T = TypeVar("T")

FallbackAction = Literal[
    "degrade_central_account_only",
    "degrade_read_only_no_archive",
    "cached_data_source",
    "degrade_no_history_replay",
    "no_fallback_break_glass",
    "advisory_only",
    "raw_json_dump",
    "reject_db_unavailable",
]


@dataclass(frozen=True)
class FallbackSpec:
    feature_id: FeatureID
    action: FallbackAction
    description: str
    has_fast_path: bool


# §5's table, verbatim.
FALLBACK_SPECS: dict[FeatureID, FallbackSpec] = {
    "F1": FallbackSpec(
        feature_id="F1",
        action="degrade_central_account_only",
        description=(
            "if scanning cross-account credentials fail, degrade to "
            "central-account-only scan; caveat noted in payload"
        ),
        has_fast_path=True,
    ),
    "F2": FallbackSpec(
        feature_id="F2",
        action="degrade_read_only_no_archive",
        description=(
            'if Access Analyzer API is down, degrade to "read-only '
            'classification" (no archive) and set archived_count=0'
        ),
        has_fast_path=True,
    ),
    "F3": FallbackSpec(
        feature_id="F3",
        action="cached_data_source",
        description=(
            "if Athena is down, use cached S3 access-log summaries from "
            "procedural memory, labeled data_source=cached in the payload"
        ),
        has_fast_path=True,
    ),
    "F4": FallbackSpec(
        feature_id="F4",
        action="degrade_no_history_replay",
        description=(
            "if history query fails, run simulation on the current chain "
            "WITHOUT historical replay; report severity capped at MEDIUM"
        ),
        has_fast_path=True,
    ),
    "F5": FallbackSpec(
        feature_id="F5",
        action="no_fallback_break_glass",
        description="no fallback -- on failure, escalate to break-glass runbook",
        has_fast_path=False,
    ),
    "F6": FallbackSpec(
        feature_id="F6",
        action="advisory_only",
        description=(
            'if SCP cache is stale, degrade to "advisory only" -- '
            "findings marked severity=INFO until cache refreshes"
        ),
        has_fast_path=True,
    ),
    "F7": FallbackSpec(
        feature_id="F7",
        action="raw_json_dump",
        description="no reasoning fallback -- falls back to raw JSON dump of the SCP chain",
        has_fast_path=True,
    ),
    "F8": FallbackSpec(
        feature_id="F8",
        action="reject_db_unavailable",
        description='if SLR DB is empty, refuse to answer -- REJECT "SLR DB unavailable"',
        has_fast_path=False,
    ),
}


class EscalatedError(SentinelAgentError):
    """Both the slow path and (if any) the fast path failed -- the caller
    must emit `verdict=ESCALATE` per §5."""

    def __init__(self, feature_id: FeatureID, *, cause: Exception) -> None:
        super().__init__(f"{feature_id}: escalated after slow+fast path failure: {cause}")
        self.feature_id = feature_id
        self.__cause__ = cause


def dispatch_with_fallback(
    *,
    feature_id: FeatureID,
    correlation_id: str,
    slow_path: Callable[[], T],
    fast_path: Callable[[], T] | None = None,
    faults_client: FaultsClient | None = None,
) -> T:
    """Tries `slow_path()`; on failure, tries `fast_path()` (if the
    specialist has one per `FALLBACK_SPECS` and the caller supplied one);
    raises `EscalatedError` if both fail or none exists (F5/F8's
    `has_fast_path=False`). Every transition writes a `FaultRecord`.
    """
    spec = FALLBACK_SPECS[feature_id]
    try:
        return slow_path()
    except Exception as slow_exc:
        if not spec.has_fast_path or fast_path is None:
            record_fault(
                correlation_id=correlation_id,
                fault_class="adapter_fault",
                origin=f"{feature_id}:slow_path",
                action_taken="escalated",
                detail=str(slow_exc),
                faults_client=faults_client,
                force_write=True,
            )
            raise EscalatedError(feature_id, cause=slow_exc) from slow_exc

        record_fault(
            correlation_id=correlation_id,
            fault_class="adapter_fault",
            origin=f"{feature_id}:slow_path",
            action_taken="fell_back",
            detail=str(slow_exc),
            faults_client=faults_client,
            force_write=True,
        )
        try:
            return fast_path()
        except Exception as fast_exc:
            record_fault(
                correlation_id=correlation_id,
                fault_class="adapter_fault",
                origin=f"{feature_id}:fast_path",
                action_taken="escalated",
                detail=str(fast_exc),
                faults_client=faults_client,
                force_write=True,
            )
            raise EscalatedError(feature_id, cause=fast_exc) from fast_exc
