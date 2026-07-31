"""`remember(kind, record)` (phase-14 §4/§Step2-3): the write side of the
shared `MemoryActions` action group.

Per phase-14 §4: "The `remember` action is restricted at the IAM policy
layer -- only Prime's post-turn Lambda writes episodic; only the syncer
writes semantic; only individual tool Lambdas write procedural. Agents
cannot write memory directly." That restriction is enforced for real by
scoped IAM policies on each Lambda's execution role (aws-infra concern).
`writer_role` here is defense-in-depth: whichever caller reaches this
module must self-identify as the one writer each kind expects, or the call
is rejected before any DDB write happens.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from iam_sentinel_agents.errors import MemoryIsolationError, MemoryWriteForbiddenError

if TYPE_CHECKING:
    from iam_sentinel_adapters.memory.client import MemoryClient

    from iam_sentinel_agents.contracts.memory import EpisodicMemory, SemanticEntity

WriterRole = str

_EPISODIC_WRITER = "prime_post_turn"
_SEMANTIC_WRITER = "semantic_syncer"
_PROCEDURAL_WRITER = "tool_memoizer"


def remember_episodic(
    memory: MemoryClient,
    record: EpisodicMemory,
    *,
    invoking_principal: str,
    writer_role: WriterRole,
) -> None:
    if writer_role != _EPISODIC_WRITER:
        raise MemoryWriteForbiddenError(
            f"writer_role {writer_role!r} may not write episodic memory "
            f"(expected {_EPISODIC_WRITER!r})"
        )
    if record.principal != invoking_principal:
        raise MemoryIsolationError(invoking_principal, record.principal)
    memory.remember_episodic(record.model_dump(mode="json"), record.correlation_id)


def upsert_semantic(
    memory: MemoryClient,
    entity: SemanticEntity,
    *,
    writer_role: WriterRole,
) -> bool:
    """Returns `True` if the write changed anything (phase-14 §3.3 change
    detection -- `MemoryClient.upsert_semantic` already sha256-compares
    against the stored body and skips the write on no-op).
    """
    if writer_role != _SEMANTIC_WRITER:
        raise MemoryWriteForbiddenError(
            f"writer_role {writer_role!r} may not write semantic memory "
            f"(expected {_SEMANTIC_WRITER!r})"
        )
    return memory.upsert_semantic(entity.model_dump(mode="json"))


def remember_procedural(
    memory: MemoryClient,
    *,
    pattern_kind: str,
    pattern_hash: str,
    result: dict[str, object],
    ttl_seconds: int,
    writer_role: WriterRole,
) -> None:
    if writer_role != _PROCEDURAL_WRITER:
        raise MemoryWriteForbiddenError(
            f"writer_role {writer_role!r} may not write procedural memory "
            f"(expected {_PROCEDURAL_WRITER!r})"
        )
    memory.procedural_put(pattern_kind, pattern_hash, result, ttl_seconds)
