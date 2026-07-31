"""`recall(kind, query, facet, top_k, pattern_kind, pattern_hash)` (phase-14
§4/§Step2): the read side of the shared `MemoryActions` action group.

Episodic recall is scoped to `invoking_principal` unconditionally -- there
is no "recall for someone else" code path, which is what makes cross-
principal contamination structurally impossible per phase-14 §3.5 rather
than merely policy-forbidden. `recall_episodic` still accepts an optional
`target_principal` (defaulting to `invoking_principal`) purely so the
isolation invariant itself is testable: passing a `target_principal` that
disagrees with `invoking_principal` raises `MemoryIsolationError` instead
of silently substituting one for the other.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from iam_sentinel_agents.contracts.memory import RecallResult
from iam_sentinel_agents.errors import MemoryIsolationError

if TYPE_CHECKING:
    from iam_sentinel_adapters.memory.client import MemoryClient


def recall_episodic(
    memory: MemoryClient,
    *,
    invoking_principal: str,
    query: str | None = None,
    top_k: int = 5,
    target_principal: str | None = None,
) -> RecallResult:
    if not invoking_principal:
        raise MemoryIsolationError("", target_principal or "")
    effective_target = target_principal or invoking_principal
    if effective_target != invoking_principal:
        raise MemoryIsolationError(invoking_principal, effective_target)

    start = time.monotonic()
    hits = memory.recall_episodic(invoking_principal, query, top_k)
    latency_ms = int((time.monotonic() - start) * 1000)
    return RecallResult(
        kind="episodic",
        hits=hits,
        latency_ms=latency_ms,
        total_scanned=len(hits),
    )


def recall_semantic(
    memory: MemoryClient,
    *,
    entity_kind: str,
    facet: dict[str, object] | None = None,
) -> RecallResult:
    start = time.monotonic()
    hits = memory.recall_semantic(entity_kind, facet or {})
    latency_ms = int((time.monotonic() - start) * 1000)
    return RecallResult(
        kind="semantic",
        hits=hits,
        latency_ms=latency_ms,
        total_scanned=len(hits),
    )


def recall_procedural(
    memory: MemoryClient,
    *,
    pattern_kind: str,
    pattern_hash: str,
) -> RecallResult:
    start = time.monotonic()
    hit = memory.procedural_get(pattern_kind, pattern_hash)
    latency_ms = int((time.monotonic() - start) * 1000)
    hits = [hit] if hit is not None else []
    return RecallResult(
        kind="procedural",
        hits=hits,
        latency_ms=latency_ms,
        total_scanned=len(hits),
    )
