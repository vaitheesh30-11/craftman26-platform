"""SessionKillPayload — F5 Session Terminator's feature payload.

Canonical source: agents/docs/phase-06-session-terminator.txt §3. F5 is the
only specialist that writes to member accounts, so unlike F1's pure-data
payload, `TerminationRecord` mirrors exactly what `tools/f5/worker.py`
persists to the `SentinelRevocations` DDB table (docs/DATA_CONTRACTS.md
§9) -- the contract and the storage row are the same shape by design so
`list_terminations` can hand DDB items straight to `TerminationRecord.
model_validate` without a translation layer.
"""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, Field

from iam_sentinel_agents.contracts.common import ACCOUNT_ID_PATTERN, ARN_PATTERN, Base

TriggerSource = Literal["guardduty", "manual", "identity_center_revoke"]


class TerminationRecord(Base):
    account_id: str = Field(pattern=ACCOUNT_ID_PATTERN)
    role_arn: str = Field(pattern=ARN_PATTERN)
    revocation_policy_name: str = Field(min_length=1, max_length=128)
    token_issue_time_cutoff: AwareDatetime
    attached_at: AwareDatetime
    ttl_expires_at: AwareDatetime
    verify_attempts: int = Field(ge=0, le=5)
    verified_attached: bool


class SessionKillPayload(Base):
    trigger_source: TriggerSource
    principal_arn: str | None = Field(default=None, pattern=ARN_PATTERN)
    permission_set_arn: str = Field(min_length=1, max_length=2048)
    reason: str = Field(min_length=1, max_length=1024)
    ttl_seconds: int = Field(ge=60, le=14_400)
    accounts_targeted: int = Field(ge=0)
    accounts_completed: int = Field(ge=0)
    accounts_failed: list[str] = Field(default_factory=list, max_length=10_000)
    terminations: list[TerminationRecord] = Field(default_factory=list, max_length=10_000)
    correlation_id: str = Field(min_length=1, max_length=256)
