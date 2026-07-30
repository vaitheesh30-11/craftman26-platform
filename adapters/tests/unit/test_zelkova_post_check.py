from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

from iam_sentinel_adapters.zelkova.models import ZelkovaResult
from iam_sentinel_adapters.zelkova.post_check import run_post_check


class _NoSuchEntityException(Exception):
    pass


def _make_iam(*, responses: list[dict[str, object] | Exception]) -> MagicMock:
    iam = MagicMock()
    iam.exceptions.NoSuchEntityException = _NoSuchEntityException
    iam.get_role_policy.side_effect = responses
    return iam


def test_post_check_mismatch_resolves_within_two_polls() -> None:
    expected = {"Version": "2012-10-17", "Statement": []}
    iam = _make_iam(
        responses=[
            {"PolicyDocument": {"Version": "2012-10-17", "Statement": [{"stale": True}]}},
            {"PolicyDocument": expected},
        ]
    )
    check_no_new_access = MagicMock(
        return_value=ZelkovaResult(
            pass_=True, result="PASS", witness=None, latency_ms=10, invoked_at=datetime.now(UTC)
        )
    )

    result = run_post_check(
        role_arn="arn:aws:iam::111111111111:role/r1",
        policy_name="inline",
        expected_policy=expected,
        wait_seconds=0,
        max_polls=3,
        correlation_id="corr-1",
        feature_id="F3",
        iam_client=iam,
        check_no_new_access=check_no_new_access,
        sleep=lambda _seconds: None,
    )

    assert result.pass_ is True
    assert iam.get_role_policy.call_count == 2
    check_no_new_access.assert_called_once_with(
        existing=expected, candidate=expected, correlation_id="corr-1", feature_id="F3"
    )


def test_post_check_fails_when_mismatch_persists_past_max_polls() -> None:
    expected = {"Version": "2012-10-17", "Statement": []}
    iam = _make_iam(
        responses=[
            {"PolicyDocument": {"Statement": [{"stale": True}]}},
            {"PolicyDocument": {"Statement": [{"stale": True}]}},
        ]
    )
    check_no_new_access = MagicMock()

    result = run_post_check(
        role_arn="arn:aws:iam::111111111111:role/r1",
        policy_name="inline",
        expected_policy=expected,
        wait_seconds=0,
        max_polls=2,
        correlation_id="corr-2",
        feature_id="F3",
        iam_client=iam,
        check_no_new_access=check_no_new_access,
        sleep=lambda _seconds: None,
    )

    assert result.pass_ is False
    assert result.witness is not None
    check_no_new_access.assert_not_called()
