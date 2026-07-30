"""RemediationPlan + ZelkovaCheck — attached to Findings that propose a mutation."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import AwareDatetime, Field, model_validator

from iam_sentinel_agents.contracts.common import Base, SHA256_PATTERN

RemediationAction = Literal[
    "attach_inline_policy",
    "detach_inline_policy",
    "update_scp",
    "archive_finding",
    "enable_cloudtrail_data_events",
    "auto_generate_policy",
]


class ZelkovaCheck(Base):
    pass_: bool = Field(alias="pass")
    witness: str | None = None
    latency_ms: int = Field(ge=0)
    invoked_at: AwareDatetime
    baseline_hash: str = Field(pattern=SHA256_PATTERN)
    candidate_hash: str = Field(pattern=SHA256_PATTERN)


class RemediationPlan(Base):
    action: RemediationAction
    target_arn: str = Field(min_length=20, max_length=2048)
    policy_document: dict[str, Any] | None = None
    ttl_seconds: int | None = Field(default=None, ge=60, le=86_400 * 30)
    dry_run: bool = True
    zelkova_pre: ZelkovaCheck | None = None
    zelkova_post: ZelkovaCheck | None = None

    @model_validator(mode="after")
    def _apply_requires_pre_check_pass(self) -> RemediationPlan:
        if not self.dry_run and self.zelkova_pre is None:
            raise ValueError("dry_run=False requires zelkova_pre to be present")
        if not self.dry_run and self.zelkova_pre is not None and not self.zelkova_pre.pass_:
            raise ValueError("dry_run=False requires zelkova_pre.pass=True")
        return self
