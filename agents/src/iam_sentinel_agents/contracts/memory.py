"""Memory Fabric contracts (phase-14 §4): the four-tier memory Pydantic
shapes shared by `recall`/`remember` tool wrappers and the semantic
syncer. Mirrors the spec's `EpisodicMemory` / `SemanticEntity` /
`ProceduralHit` / `RecallResult` verbatim, adding only field constraints
consistent with every other contract in this package (bounded strings,
non-negative counters).
"""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, Field

from iam_sentinel_agents.contracts.common import Base, FeatureID, SHA256_PATTERN
from iam_sentinel_agents.contracts.evidence import EvidenceRef

MemoryKind = Literal["episodic", "semantic", "procedural"]
SemanticEntityKind = Literal[
    "account", "ou", "role", "permission_set", "slr", "policy", "service_principal", "tag"
]


class EpisodicMemory(Base):
    principal: str = Field(min_length=1, max_length=2048)
    decision_id: str = Field(min_length=1, max_length=256)
    correlation_id: str = Field(min_length=1, max_length=256)
    feature_ids_involved: list[FeatureID] = Field(min_length=1, max_length=8)
    finding_summary: str = Field(max_length=1024)
    narrative_excerpt: str = Field(max_length=2048)
    evidence_ref: EvidenceRef
    tags: dict[str, str] = Field(default_factory=dict)
    decided_at: AwareDatetime


class SemanticEntity(Base):
    entity_kind: SemanticEntityKind
    entity_key: str = Field(min_length=1, max_length=2048)
    body: dict[str, object]
    synced_at: AwareDatetime
    source_of_truth: str = Field(min_length=1, max_length=256)
    related_entities: list[str] = Field(default_factory=list, max_length=256)
    body_sha256: str = Field(pattern=SHA256_PATTERN)


class ProceduralHit(Base):
    pattern_kind: str = Field(min_length=1, max_length=256)
    pattern_hash: str = Field(pattern=SHA256_PATTERN)
    result: dict[str, object]
    ttl: int = Field(gt=0)
    first_computed_at: AwareDatetime
    last_hit_at: AwareDatetime
    hit_count: int = Field(ge=1)


class RecallResult(Base):
    kind: MemoryKind
    hits: list[dict[str, object]] = Field(default_factory=list, max_length=50)
    latency_ms: int = Field(ge=0)
    total_scanned: int = Field(ge=0)
