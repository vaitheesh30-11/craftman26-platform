"""`tools.common.retry` (agents phase-17 §3/§4/§14) -- fault-taxonomy-aware
wrapper around `iam_sentinel_adapters.retry`'s already-real backoff/cap
mechanics. §12 Test Plan: "each retry policy applied against a stubbed
throttle sequence; verify attempts and total wait time within jitter."
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest
from iam_sentinel_adapters.errors import AccessDeniedError, ThrottlingError
from iam_sentinel_adapters.retry import Policy

from iam_sentinel_agents.tools.common.retry import (
    ADAPTER_CALL_SITE_POLICY,
    record_fault,
    RetryExhausted,
    should_sample,
    with_fault_recording,
)

pytestmark = pytest.mark.unit


def test_should_sample_always_true_for_non_transient_classes() -> None:
    assert should_sample("adapter_fault", rng=lambda: 0.99)
    assert should_sample("model_fault", rng=lambda: 0.99)


def test_should_sample_is_1_percent_for_transient_throttling() -> None:
    assert should_sample("transient_throttling", rng=lambda: 0.005)
    assert not should_sample("transient_throttling", rng=lambda: 0.5)


def test_record_fault_writes_via_faults_client() -> None:
    faults_client = MagicMock()

    record = record_fault(
        correlation_id="01ABCDEF",
        fault_class="adapter_fault",
        origin="test:origin",
        action_taken="escalated",
        detail="boom",
        faults_client=faults_client,
        force_write=True,
    )

    assert record is not None
    faults_client.put.assert_called_once()
    written = faults_client.put.call_args.args[0]
    assert written["correlation_id"] == "01ABCDEF"
    assert written["fault_class"] == "adapter_fault"
    assert written["action_taken"] == "escalated"


def test_record_fault_drops_write_when_sampling_excludes_it() -> None:
    faults_client = MagicMock()

    record = record_fault(
        correlation_id="01ABCDEF",
        fault_class="transient_throttling",
        origin="test:origin",
        action_taken="retried",
        detail="throttled",
        faults_client=faults_client,
        rng=lambda: 0.5,
    )

    assert record is None
    faults_client.put.assert_not_called()


def test_with_fault_recording_succeeds_after_transient_failures_and_records_retried() -> None:
    faults_client = MagicMock()
    calls = 0

    @with_fault_recording(
        policy=Policy.AGGRESSIVE,
        fault_class="adapter_fault",
        origin="test:flaky",
        retry_on=(ThrottlingError,),
        faults_client=faults_client,
    )
    def flaky(*, correlation_id: str) -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise ThrottlingError("throttled")
        return "ok"

    start = time.monotonic()
    result = flaky(correlation_id="01FLAKY")
    elapsed = time.monotonic() - start

    assert result == "ok"
    assert calls == 3
    # AGGRESSIVE's own total_time_cap bounds worst case; 3 short waits
    # (base 0.2s, factor 2) complete well under a second in practice.
    assert elapsed < Policy.AGGRESSIVE.total_time_cap

    faults_client.put.assert_called_once()
    written = faults_client.put.call_args.args[0]
    assert written["action_taken"] == "retried"
    assert written["correlation_id"] == "01FLAKY"


def test_with_fault_recording_exhausts_and_raises_retry_exhausted() -> None:
    faults_client = MagicMock()

    @with_fault_recording(
        policy=Policy.SINGLE,
        fault_class="transient_network",
        origin="test:always_fails",
        retry_on=(ThrottlingError,),
        faults_client=faults_client,
    )
    def always_fails(*, correlation_id: str) -> str:
        raise ThrottlingError("still throttled")

    with pytest.raises(RetryExhausted) as exc_info:
        always_fails(correlation_id="01EXHAUST")

    assert exc_info.value.fault_class == "transient_network"
    assert exc_info.value.attempts == 2  # SINGLE = 1 retry after the first attempt

    faults_client.put.assert_called_once()
    written = faults_client.put.call_args.args[0]
    assert written["action_taken"] == "escalated"
    assert written["fault_class"] == "transient_network"


def test_with_fault_recording_never_retries_a_non_retryable_error() -> None:
    faults_client = MagicMock()
    calls = 0

    @with_fault_recording(
        policy=Policy.AGGRESSIVE,
        fault_class="adapter_fault",
        origin="test:denied",
        retry_on=(ThrottlingError,),
        faults_client=faults_client,
    )
    def denied(*, correlation_id: str) -> str:
        nonlocal calls
        calls += 1
        raise AccessDeniedError("nope")

    with pytest.raises(AccessDeniedError):
        denied(correlation_id="01DENIED")

    assert calls == 1
    faults_client.put.assert_not_called()


def test_with_fault_recording_writes_nothing_when_no_retry_was_needed() -> None:
    faults_client = MagicMock()

    @with_fault_recording(
        policy=Policy.AGGRESSIVE,
        fault_class="adapter_fault",
        origin="test:first_try",
        retry_on=(ThrottlingError,),
        faults_client=faults_client,
    )
    def works(*, correlation_id: str) -> str:
        return "ok"

    assert works(correlation_id="01FIRSTTRY") == "ok"
    faults_client.put.assert_not_called()


def test_adapter_call_site_policy_table_covers_every_spec_4_assignment() -> None:
    # §4's assignments table names 6 adapter call sites; each maps to a
    # (Policy, FaultClass) pair here rather than being hardcoded per caller.
    assert ADAPTER_CALL_SITE_POLICY["bedrock_invoke_throttling"] == (
        Policy.AGGRESSIVE,
        "transient_throttling",
    )
    assert ADAPTER_CALL_SITE_POLICY["bedrock_invoke_validation"] == (Policy.NONE, "model_fault")
    assert ADAPTER_CALL_SITE_POLICY["sts_assume_role_throttling"] == (
        Policy.AGGRESSIVE,
        "transient_throttling",
    )
    assert ADAPTER_CALL_SITE_POLICY["sts_assume_role_access_denied"] == (
        Policy.NONE,
        "adapter_fault",
    )
    assert ADAPTER_CALL_SITE_POLICY["ddb_put_update_throttling"] == (
        Policy.AGGRESSIVE,
        "transient_throttling",
    )
    assert ADAPTER_CALL_SITE_POLICY["ddb_put_update_provisioned_exceeded"] == (
        Policy.SINGLE,
        "transient_throttling",
    )
    assert ADAPTER_CALL_SITE_POLICY["athena_start_query_too_many_requests"] == (
        Policy.CAUTIOUS,
        "transient_throttling",
    )
    assert ADAPTER_CALL_SITE_POLICY["athena_start_query_invalid_request"] == (
        Policy.NONE,
        "logic_fault",
    )
    assert ADAPTER_CALL_SITE_POLICY["iam_put_role_policy"] == (Policy.SINGLE, "adapter_fault")
