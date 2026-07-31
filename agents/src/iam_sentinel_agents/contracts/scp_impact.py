"""ScpImpactPayload -- F4 SCP Impact Analyst's feature payload.

Canonical source: agents/docs/phase-05-scp-impact-analyst.txt SS3. Pure data
contract, mirroring F1's `contracts/passrole.py` precedent: nothing in
`tools/f4/` is required to construct a `ScpImpactPayload` at runtime (the
Bedrock Agent itself assembles `Finding.payload` from the three tools' JSON
responses per the specialist prompt's REASONING CONTRACT) -- `tools/f4/
simulate.build_impact_payload` exists so tests can exercise the whole
pipeline against one concrete object instead of asserting on loose dicts.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from iam_sentinel_agents.contracts.common import ARN_PATTERN, Base

_SCP_TARGET_PATTERN = r"^(ou-[a-z0-9-]+|[0-9]{12}|r-[a-z0-9]+)$"

DenyingLevel = Literal["root", "ou", "account"]


class BlockedInvocation(Base):
    role_arn: str = Field(pattern=ARN_PATTERN)
    action: str = Field(min_length=1, max_length=256)
    event_source: str = Field(min_length=1, max_length=256)
    call_count_last_90_days: int = Field(ge=0)
    denying_scp_arn: str = Field(min_length=1, max_length=2048)
    denying_statement_id: str | None = None
    denying_level: DenyingLevel


class SuggestedExemption(Base):
    statement_to_add: dict[str, object]
    rationale: str = Field(min_length=1, max_length=2048)
    references_service: str | None = None


class ScpImpactPayload(Base):
    proposed_scp_target: str = Field(pattern=_SCP_TARGET_PATTERN)
    proposed_scp: dict[str, object]
    proposed_scp_bytes: int = Field(ge=0)
    total_calls_analyzed: int = Field(ge=0)
    calls_that_would_be_blocked: int = Field(ge=0)
    impacted_roles: list[BlockedInvocation] = Field(default_factory=list, max_length=10_000)
    suggested_exemptions: list[SuggestedExemption] = Field(default_factory=list, max_length=10_000)
    scp_chain: list[dict[str, object]] = Field(default_factory=list, max_length=32)
    engine_version: str = Field(min_length=1, max_length=32)
