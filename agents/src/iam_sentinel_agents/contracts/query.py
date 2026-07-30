"""SentinelQuery — user-facing entry contract for API Gateway and CLI."""

from __future__ import annotations

from datetime import datetime, timedelta, UTC

from pydantic import AwareDatetime, Field, field_validator

from iam_sentinel_agents.contracts.common import ARN_PATTERN, Base, ULID_PATTERN

_MAX_HINTS = 16
_MAX_HINT_KEY_LENGTH = 64
_MAX_HINT_VALUE_LENGTH = 512


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
        if len(value) > _MAX_HINTS:
            raise ValueError(f"hints capped at {_MAX_HINTS} entries")
        for key, val in value.items():
            if len(key) > _MAX_HINT_KEY_LENGTH or len(val) > _MAX_HINT_VALUE_LENGTH:
                raise ValueError(
                    f"hint key ≤ {_MAX_HINT_KEY_LENGTH} chars, "
                    f"value ≤ {_MAX_HINT_VALUE_LENGTH} chars"
                )
        return value

    @field_validator("submitted_at")
    @classmethod
    def _submitted_not_in_future(cls, value: datetime) -> datetime:
        now = datetime.now(UTC)
        if value > now + timedelta(minutes=5):
            raise ValueError("submitted_at cannot be more than 5 minutes in the future")
        return value
