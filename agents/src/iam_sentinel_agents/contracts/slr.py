"""SlrImpactPayload -- F8 SLR Guardian's feature payload.

Canonical source: agents/docs/phase-09-slr-guardian.txt §3. Pure data
contract: `tools/f8/scan.evaluate_scp` returns a plain dict shaped exactly
like this payload (the Bedrock Agent validates/re-serializes it into
`Finding.payload` per the specialist prompt's REASONING CONTRACT) -- this
module exists so tests can assert against one concrete, validated object
instead of loose dicts.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from iam_sentinel_agents.contracts.common import Base

Impact = Literal["CRITICAL", "HIGH", "MEDIUM"]


class SlrConflict(Base):
    service_principal: str = Field(min_length=1, max_length=256)
    slr_name: str = Field(min_length=1, max_length=256)
    blocked_actions: list[str] = Field(default_factory=list, max_length=10_000)
    impact: Impact
    proposed_exemption_statement: dict[str, object]
    alternative_condition: dict[str, object] | None = None


class SlrImpactPayload(Base):
    proposed_scp: dict[str, object]
    proposed_scp_bytes: int = Field(ge=0)
    slr_db_version: str = Field(min_length=1, max_length=64)
    total_slrs_checked: int = Field(ge=0)
    conflicts: list[SlrConflict] = Field(default_factory=list, max_length=10_000)
    safe_scp: dict[str, object]
    safe_scp_bytes: int = Field(ge=0)
    exceeds_size_limit: bool
