"""DecisionRecord — Prime's synthesis, persisted to DDB and Security Hub."""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, Field

from iam_sentinel_agents.contracts.common import ARN_PATTERN, ULID_PATTERN, Base
from iam_sentinel_agents.contracts.evidence import EvidenceRef
from iam_sentinel_agents.contracts.finding import Finding
from iam_sentinel_agents.contracts.query import SentinelQuery
from iam_sentinel_agents.contracts.remediation import RemediationPlan
from iam_sentinel_agents.contracts.verdict import SpecialistVerdict


class DecisionRecord(Base):
    decision_id: str = Field(pattern=ULID_PATTERN)
    correlation_id: str = Field(pattern=ULID_PATTERN)
    principal: str = Field(pattern=ARN_PATTERN)
    query: SentinelQuery
    specialist_verdicts: list[SpecialistVerdict] = Field(min_length=1, max_length=8)
    findings: list[Finding] = Field(default_factory=list, max_length=100)
    remediations_proposed: list[RemediationPlan] = Field(default_factory=list, max_length=32)
    remediations_applied: list[RemediationPlan] = Field(default_factory=list, max_length=32)
    status: Literal["ANSWERED", "ESCALATED", "AUTO_REMEDIATED", "REJECTED"]
    narrative: str = Field(min_length=1, max_length=16_384)
    evidence_ref: EvidenceRef
    decided_at: AwareDatetime
