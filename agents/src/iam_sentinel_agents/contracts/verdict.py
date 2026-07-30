"""SpecialistVerdict — Specialist → Supervisor return contract."""

from __future__ import annotations

from pydantic import Field, model_validator

from iam_sentinel_agents.contracts.common import (
    Base,
    FeatureID,
    SHA256_PATTERN,
    ULID_PATTERN,
    Verdict,
)
from iam_sentinel_agents.contracts.finding import Finding
from iam_sentinel_agents.contracts.remediation import RemediationPlan, ZelkovaCheck


class ToolInvocation(Base):
    tool_name: str = Field(min_length=1, max_length=128)
    input_hash: str = Field(pattern=SHA256_PATTERN)
    output_hash: str = Field(pattern=SHA256_PATTERN)
    duration_ms: int = Field(ge=0)
    zelkova_check: ZelkovaCheck | None = None


class SpecialistVerdict(Base):
    correlation_id: str = Field(pattern=ULID_PATTERN)
    feature_id: FeatureID
    verdict: Verdict
    reason: str = Field(min_length=1, max_length=2048)
    findings: list[Finding] = Field(default_factory=list, max_length=100)
    remediation: RemediationPlan | None = None
    tool_invocations: list[ToolInvocation] = Field(default_factory=list, max_length=32)
    duration_ms: int = Field(ge=0)

    @model_validator(mode="after")
    def _confirm_with_mutation_requires_zelkova(self) -> SpecialistVerdict:
        if self.verdict != "CONFIRM" or self.remediation is None:
            return self
        if self.remediation.dry_run:
            return self
        mutating_calls = [t for t in self.tool_invocations if t.zelkova_check is not None]
        all_passed = all(call.zelkova_check.pass_ for call in mutating_calls if call.zelkova_check)
        if not mutating_calls or not all_passed:
            raise ValueError(
                "CONFIRM with a non-dry-run remediation requires every mutating "
                "tool invocation to carry a passing Zelkova check"
            )
        return self
