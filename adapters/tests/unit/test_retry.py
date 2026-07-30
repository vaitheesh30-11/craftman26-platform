from __future__ import annotations

import pytest

from iam_sentinel_adapters.errors import AccessDeniedError, ThrottlingError
from iam_sentinel_adapters.retry import Policy, retry


def test_single_policy_runs_exactly_two_attempts() -> None:
    calls = 0

    @retry(policy=Policy.SINGLE)
    def flaky() -> str:
        nonlocal calls
        calls += 1
        raise ThrottlingError("throttled")

    with pytest.raises(ThrottlingError):
        flaky()

    assert calls == 2


def test_none_policy_runs_exactly_one_attempt() -> None:
    calls = 0

    @retry(policy=Policy.NONE)
    def flaky() -> str:
        nonlocal calls
        calls += 1
        raise ThrottlingError("throttled")

    with pytest.raises(ThrottlingError):
        flaky()

    assert calls == 1


def test_retry_succeeds_after_transient_failures() -> None:
    calls = 0

    @retry(policy=Policy.AGGRESSIVE)
    def flaky() -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise ThrottlingError("throttled")
        return "ok"

    assert flaky() == "ok"
    assert calls == 3


def test_non_retryable_error_short_circuits_immediately() -> None:
    calls = 0

    @retry(policy=Policy.AGGRESSIVE)
    def denied() -> str:
        nonlocal calls
        calls += 1
        raise AccessDeniedError("nope")

    with pytest.raises(AccessDeniedError):
        denied()

    assert calls == 1
