"""`DataEventPolicyPayload`/`S3DataEventUsage` — round-trip and extra-forbid,
mirroring the contract-suite convention in `tests/contract/` but scoped to
this feature's own test package (same shape as F1's `PassRoleBlastPayload`
not being added to the shared `tests/contract/_factories.py` list either).
"""

from __future__ import annotations

from datetime import datetime, UTC

import pytest
from pydantic import ValidationError

from iam_sentinel_agents.contracts.data_event import DataEventPolicyPayload, S3DataEventUsage
from iam_sentinel_agents.contracts.remediation import ZelkovaCheck

pytestmark = pytest.mark.unit

_ROLE_ARN = "arn:aws:iam::111122223333:role/DataPipeline"


def _payload() -> DataEventPolicyPayload:
    usage = S3DataEventUsage(
        action="s3:GetObject",
        bucket="reports",
        prefixes=["2026/01/a.json"],
        consolidated_prefix="2026/*",
        call_count=8,
    )
    zelkova_pre = ZelkovaCheck(
        **{"pass": True},
        witness=None,
        latency_ms=15,
        invoked_at=datetime(2026, 7, 30, tzinfo=UTC),
        baseline_hash="0" * 64,
        candidate_hash="1" * 64,
    )
    return DataEventPolicyPayload(
        role_arn=_ROLE_ARN,
        days_back=30,
        base_policy={"Version": "2012-10-17", "Statement": []},
        data_event_usage=[usage],
        merged_policy={"Version": "2012-10-17", "Statement": []},
        merged_policy_bytes=64,
        truncated=False,
        zelkova_pre=zelkova_pre,
    )


def test_roundtrip_is_lossless() -> None:
    original = _payload()
    restored = DataEventPolicyPayload.model_validate_json(original.model_dump_json(by_alias=True))
    assert restored == original


def test_unknown_field_is_rejected() -> None:
    payload = _payload().model_dump(mode="json")
    payload["definitely_not_a_real_field"] = "surprise!"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        DataEventPolicyPayload.model_validate(payload)


def test_days_back_out_of_range_is_rejected() -> None:
    payload = _payload().model_dump(mode="json")
    payload["days_back"] = 91
    with pytest.raises(ValidationError):
        DataEventPolicyPayload.model_validate(payload)
