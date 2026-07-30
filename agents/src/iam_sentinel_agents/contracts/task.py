"""SpecialistTask — Supervisor → Specialist handoff contract."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from iam_sentinel_agents.contracts.common import ULID_PATTERN, Base, FeatureID


class UntrustedContextBlock(Base):
    type: str = Field(min_length=1, max_length=64, pattern=r"^[a-z_]+$")
    body: str = Field(max_length=32_768)


class SpecialistTask(Base):
    correlation_id: str = Field(pattern=ULID_PATTERN)
    feature_id: FeatureID
    tool_hint: str | None = None
    trusted_input: dict[str, Any] = Field(default_factory=dict)
    untrusted_context: list[UntrustedContextBlock] = Field(default_factory=list, max_length=16)
    retry_count: int = Field(ge=0, le=2, default=0)
