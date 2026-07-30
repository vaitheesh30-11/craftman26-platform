"""SentinelQuery — user-facing entry contract for API Gateway and CLI."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from pydantic import AwareDatetime, Field, field_validator

from iam_sentinel_agents.contracts.common import ARN_PATTERN, Base, ULID_PATTERN


class SentinelQuery(Base):
    correlation_id: str = Field(pattern=ULID_PATTERN)
    principal: str = Field(pattern=ARN_PATTERN, min_length=20, max_length=2048)
    query_text: str = Field(min_length=1, max_length=4096)
    hints: dict[str, str] = Field(default_factory=dict)
    include_arns_in_output: bool = False
    submitted_at: AwareDatetime

    @field_validator("hints")
    @classmethod
    def _hints_size_cap(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > 16:
            raise ValueError("hints capped at 16 entries")
        for key, val in value.items():
            if len(key) > 64 or len(val) > 512:
                raise ValueError("hint key ≤ 64 chars, value ≤ 512 chars")
        return value

    @field_validator("submitted_at")
    @classmethod
    def _submitted_not_in_future(cls, value: datetime) -> datetime:
        now = datetime.now(timezone.utc)
        if value > now + timedelta(minutes=5):
            raise ValueError("submitted_at cannot be more than 5 minutes in the future")
        return value
