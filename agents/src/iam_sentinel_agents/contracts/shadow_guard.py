"""ShadowViolationPayload -- F6 Shadow Guard's feature payload.

Canonical source: agents/docs/phase-07-shadow-guard.txt §3. Pure data
contracts: `tools/f6/report.build_shadow_violation_payload` exists so tests
can exercise the aggregation pipeline against one concrete object instead of
asserting on loose dicts, mirroring F1's `PassRoleBlastPayload` precedent
(`contracts/passrole.py`).
"""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, Field

from iam_sentinel_agents.contracts.common import ARN_PATTERN, Base, Severity

PrincipalType = Literal["Root", "IAMUser", "AssumedRole", "FederatedUser"]
DeniedAtLevel = Literal["root", "ou"]
ControlKind = Literal["EventBridgeRule", "ConfigRule"]


class ShadowViolation(Base):
    action: str = Field(min_length=1, max_length=256)
    principal_arn: str = Field(pattern=ARN_PATTERN)
    principal_type: PrincipalType
    would_be_denied_by_scp_arn: str = Field(min_length=1, max_length=2048)
    denying_statement_id: str | None = None
    would_be_denied_at_level: DeniedAtLevel
    event_id: str = Field(min_length=1, max_length=128)
    event_time: AwareDatetime
    severity: Severity


class ShadowViolationPayload(Base):
    days_back: int = Field(ge=1, le=30)
    total_events_ingested: int = Field(ge=0)
    violation_count: int = Field(ge=0)
    violations: list[ShadowViolation] = Field(default_factory=list, max_length=10_000)
    top_actions: list[dict[str, object]] = Field(default_factory=list, max_length=10)
    weekly_trend: dict[str, int] | None = None


class CompensatingControl(Base):
    for_action: str = Field(min_length=1, max_length=256)
    control_kind: ControlKind
    cdk_snippet: str = Field(min_length=1, max_length=16_384)
    rationale: str = Field(min_length=1, max_length=2048)
