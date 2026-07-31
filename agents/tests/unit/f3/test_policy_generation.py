"""base_policy_generate + Zelkova pre-check helper — phase-04 §4 Steps 5, 7."""

from __future__ import annotations

from datetime import datetime, UTC
from typing import Any
from unittest.mock import MagicMock

import pytest
from iam_sentinel_adapters.zelkova.models import PolicyPair, Witness, ZelkovaResult

from iam_sentinel_agents.tools.f3.policy_generation import (
    generate_base_policy,
    PolicyGenerationTimeoutError,
    zelkova_precheck,
)

pytestmark = pytest.mark.unit

_BASE_POLICY: dict[str, Any] = {"Version": "2012-10-17", "Statement": []}


def test_generate_base_policy_polls_until_ready() -> None:
    zelkova = MagicMock()
    zelkova.start_policy_generation.return_value = "job-1"
    zelkova.get_generated_policy.side_effect = [None, None, _BASE_POLICY]
    sleeps: list[float] = []

    result = generate_base_policy(
        role_arn="arn:aws:iam::111122223333:role/DataPipeline",
        cloudtrail_details={"Trails": []},
        zelkova=zelkova,
        correlation_id="c1",
        sleep=sleeps.append,
    )

    assert result == _BASE_POLICY
    assert len(sleeps) == 2
    assert zelkova.get_generated_policy.call_count == 3


def test_generate_base_policy_times_out_when_never_ready() -> None:
    zelkova = MagicMock()
    zelkova.start_policy_generation.return_value = "job-2"
    zelkova.get_generated_policy.return_value = None

    with pytest.raises(PolicyGenerationTimeoutError):
        generate_base_policy(
            role_arn="arn:aws:iam::111122223333:role/DataPipeline",
            cloudtrail_details={"Trails": []},
            zelkova=zelkova,
            correlation_id="c2",
            sleep=lambda _seconds: None,
        )


def test_zelkova_precheck_runs_both_checks_and_persists_the_gating_result() -> None:
    zelkova = MagicMock()
    baseline_check = ZelkovaResult(
        pass_=True,
        result="PASS",
        witness=None,
        latency_ms=10,
        invoked_at=datetime.now(UTC),
        policy_pair=PolicyPair(
            existing={}, candidate=_BASE_POLICY, existing_sha256="0" * 64, candidate_sha256="1" * 64
        ),
    )
    gating_check = ZelkovaResult(
        pass_=False,
        result="FAIL",
        witness=Witness(
            principal="role/x", action="s3:GetObject", resource="arn:aws:s3:::bucket/*"
        ),
        latency_ms=20,
        invoked_at=datetime.now(UTC),
        policy_pair=PolicyPair(
            existing=_BASE_POLICY, candidate={}, existing_sha256="1" * 64, candidate_sha256="2" * 64
        ),
    )
    zelkova.check_no_new_access.side_effect = [baseline_check, gating_check]

    result = zelkova_precheck(
        base_policy=_BASE_POLICY,
        merged_policy={"Version": "2012-10-17", "Statement": []},
        zelkova=zelkova,
        correlation_id="c3",
    )

    assert zelkova.check_no_new_access.call_count == 2
    assert result.pass_ is False
    assert result.witness == "role/x s3:GetObject arn:aws:s3:::bucket/*"
    assert result.baseline_hash == "1" * 64
    assert result.candidate_hash == "2" * 64
