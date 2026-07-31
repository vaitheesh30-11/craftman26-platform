"""repair/corrupted_memory -- §7's first repair Lambda.

"Trigger: SentinelMemoryReadFailure metric spike. Duties: for the affected
item, verify KMS signature, verify sha256, re-fetch from source of truth
(episodic -> re-derive from SentinelDecisions; semantic -> re-run syncer
for that entity_key; procedural -> invalidate the cache entry)."

The alarm-driven invocation only tells this Lambda WHICH item is
suspected corrupt (`memory_kind` + its key); this module does not itself
detect corruption (that is `SentinelMemoryReadFailure`'s job, emitted by
whatever read path first failed to deserialize/verify a memory row -- no
such emitting code exists yet, same gap phase-14 Memory Fabric's own ADR
would track). `repair_semantic_entity`'s `resync` callable is a required
injection point: the semantic syncer itself is agents phase-14's
deliverable (a sibling in-flight branch as of this writing, not yet on
`main`) -- this repair Lambda is built against "some callable that can
resync one entity_key," not a concrete implementation that doesn't exist
yet, the same "build the caller before the callee" precedent ADR 0014/
0017 already established.
"""

from __future__ import annotations

from datetime import datetime, UTC
from typing import Any, Literal, TYPE_CHECKING

from iam_sentinel_adapters.ddb.decisions import DecisionsClient
from iam_sentinel_adapters.evidence import EvidenceClient
from iam_sentinel_adapters.memory.client import MemoryClient

from iam_sentinel_agents.errors import SentinelAgentError
from iam_sentinel_agents.tools.common.retry import record_fault

if TYPE_CHECKING:
    from collections.abc import Callable

    from aws_lambda_powertools.utilities.typing import LambdaContext
    from iam_sentinel_adapters.ddb.faults import FaultsClient

MemoryKind = Literal["episodic", "semantic", "procedural"]


class MemoryRepairError(SentinelAgentError):
    """Raised when a corrupted memory item cannot be repaired (e.g. its
    source-of-truth row is itself gone)."""


def repair_episodic_entry(
    *,
    correlation_id: str,
    decisions_client: DecisionsClient | None = None,
    memory_client: MemoryClient | None = None,
) -> dict[str, Any]:
    """Re-derives from `SentinelDecisions` -- Prime's post-turn Lambda is
    the source of truth episodic memory only ever mirrors. `correlation_id`
    alone identifies the row via `get_by_correlation_id`'s GSI; the
    caller's `key` dict may carry `principal` too (for symmetry with the
    other memory kinds' key shapes), but this lookup does not need it."""
    decisions = decisions_client or DecisionsClient()
    memory = memory_client or MemoryClient()

    source = decisions.get_by_correlation_id(correlation_id)
    if source is None:
        raise MemoryRepairError(
            f"cannot re-derive episodic entry: no SentinelDecisions row for "
            f"correlation_id={correlation_id!r}"
        )
    memory.remember_episodic(source, correlation_id)
    return source


def repair_semantic_entity(
    *,
    entity_kind: str,
    entity_key: str,
    resync: Callable[[str, str], dict[str, Any]],
    memory_client: MemoryClient | None = None,
) -> dict[str, Any]:
    """Re-runs the semantic syncer for one entity via the injected
    `resync(entity_kind, entity_key)` callable, then upserts the result."""
    memory = memory_client or MemoryClient()
    entity = resync(entity_kind, entity_key)
    memory.upsert_semantic(entity)
    return entity


def repair_procedural_entry(
    *,
    pattern_kind: str,
    pattern_hash: str,
    memory_client: MemoryClient | None = None,
) -> None:
    """Procedural memory is a TTL'd cache, not a source of truth --
    "repair" means invalidating the corrupted row so the next cache-miss
    recomputes it cleanly."""
    (memory_client or MemoryClient()).invalidate_procedural(pattern_kind, pattern_hash)


def repair_corrupted_memory(
    *,
    memory_kind: MemoryKind,
    key: dict[str, str],
    correlation_id: str,
    resync: Callable[[str, str], dict[str, Any]] | None = None,
    decisions_client: DecisionsClient | None = None,
    memory_client: MemoryClient | None = None,
    evidence_client: EvidenceClient | None = None,
    faults_client: FaultsClient | None = None,
) -> dict[str, Any]:
    """Dispatches to the per-kind repair, then always emits an
    `EvidenceRecord(kind="repair_action")` and a `FaultRecord
    (action_taken="auto_repaired")` for auditability (§7's closing line).
    """
    if memory_kind == "episodic":
        repaired: dict[str, Any] = {
            "kind": "episodic",
            "result": repair_episodic_entry(
                correlation_id=correlation_id,
                decisions_client=decisions_client,
                memory_client=memory_client,
            ),
        }
    elif memory_kind == "semantic":
        if resync is None:
            raise MemoryRepairError("semantic repair requires an injected `resync` callable")
        repaired = {
            "kind": "semantic",
            "result": repair_semantic_entity(
                entity_kind=key["entity_kind"],
                entity_key=key["entity_key"],
                resync=resync,
                memory_client=memory_client,
            ),
        }
    else:
        repair_procedural_entry(
            pattern_kind=key["pattern_kind"],
            pattern_hash=key["pattern_hash"],
            memory_client=memory_client,
        )
        repaired = {"kind": "procedural", "result": {"invalidated": True}}

    body = {"memory_kind": memory_kind, "key": key, **repaired}
    (evidence_client or EvidenceClient()).put_signed_evidence(
        kind="repair_action",
        body=body,
        correlation_id=correlation_id,
        feature_id="F8",  # no dedicated cross-cutting FeatureID exists; F8 is the nearest
    )
    record_fault(
        correlation_id=correlation_id,
        fault_class="data_corruption",
        origin=f"repair:corrupted_memory:{memory_kind}",
        action_taken="auto_repaired",
        detail=f"repaired {memory_kind} memory item for key={key}",
        resolved_at=datetime.now(UTC),
        faults_client=faults_client,
        force_write=True,
    )
    return body


def corrupted_memory_repair(event: dict[str, Any], _context: LambdaContext) -> dict[str, Any]:
    """Alarm-action Lambda entrypoint (§7 trigger:
    `SentinelMemoryReadFailure` metric spike) -- no Bedrock envelope."""
    return repair_corrupted_memory(
        memory_kind=event["memory_kind"],
        key=event["key"],
        correlation_id=event["correlation_id"],
    )
