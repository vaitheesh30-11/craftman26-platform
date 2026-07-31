"""`tools.common.fallback` (agents phase-17 §5). §12 Test Plan: "for each
specialist, simulate slow-path failure; verify fast path invoked; verify
escalation on both-fail."
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from iam_sentinel_agents.tools.common.fallback import (
    dispatch_with_fallback,
    EscalatedError,
    FALLBACK_SPECS,
)

pytestmark = pytest.mark.unit

_ALL_FEATURE_IDS = ("F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8")


def test_fallback_specs_cover_every_specialist() -> None:
    assert set(FALLBACK_SPECS) == set(_ALL_FEATURE_IDS)


def test_f5_and_f8_have_no_fast_path_per_spec() -> None:
    assert FALLBACK_SPECS["F5"].has_fast_path is False
    assert FALLBACK_SPECS["F8"].has_fast_path is False


@pytest.mark.parametrize("feature_id", ["F1", "F2", "F3", "F4", "F6", "F7"])
def test_slow_path_success_never_touches_fast_path(feature_id: str) -> None:
    faults_client = MagicMock()
    fast_path = MagicMock()

    result = dispatch_with_fallback(
        feature_id=feature_id,  # type: ignore[arg-type]
        correlation_id="01SLOWOK",
        slow_path=lambda: "slow-result",
        fast_path=fast_path,
        faults_client=faults_client,
    )

    assert result == "slow-result"
    fast_path.assert_not_called()
    faults_client.put.assert_not_called()


@pytest.mark.parametrize("feature_id", ["F1", "F2", "F3", "F4", "F6", "F7"])
def test_slow_path_failure_invokes_fast_path_and_records_fell_back(feature_id: str) -> None:
    faults_client = MagicMock()

    result = dispatch_with_fallback(
        feature_id=feature_id,  # type: ignore[arg-type]
        correlation_id="01FELLBACK",
        slow_path=MagicMock(side_effect=RuntimeError("slow path down")),
        fast_path=lambda: "fast-result",
        faults_client=faults_client,
    )

    assert result == "fast-result"
    assert faults_client.put.call_count == 1
    written = faults_client.put.call_args.args[0]
    assert written["action_taken"] == "fell_back"


@pytest.mark.parametrize("feature_id", ["F1", "F2", "F3", "F4", "F6", "F7"])
def test_both_paths_failing_raises_escalated_error(feature_id: str) -> None:
    faults_client = MagicMock()

    with pytest.raises(EscalatedError) as exc_info:
        dispatch_with_fallback(
            feature_id=feature_id,  # type: ignore[arg-type]
            correlation_id="01BOTHFAIL",
            slow_path=MagicMock(side_effect=RuntimeError("slow path down")),
            fast_path=MagicMock(side_effect=RuntimeError("fast path down too")),
            faults_client=faults_client,
        )

    assert exc_info.value.feature_id == feature_id
    assert faults_client.put.call_count == 2
    actions = [call.args[0]["action_taken"] for call in faults_client.put.call_args_list]
    assert actions == ["fell_back", "escalated"]


@pytest.mark.parametrize("feature_id", ["F5", "F8"])
def test_no_fallback_specialists_escalate_immediately_without_a_fast_path(
    feature_id: str,
) -> None:
    faults_client = MagicMock()
    fast_path = MagicMock()

    with pytest.raises(EscalatedError):
        dispatch_with_fallback(
            feature_id=feature_id,  # type: ignore[arg-type]
            correlation_id="01NOFALLBACK",
            slow_path=MagicMock(side_effect=RuntimeError("slow path down")),
            fast_path=fast_path,
            faults_client=faults_client,
        )

    fast_path.assert_not_called()
    assert faults_client.put.call_count == 1
    assert faults_client.put.call_args.args[0]["action_taken"] == "escalated"


def test_no_fallback_specialist_escalates_even_without_a_fast_path_argument() -> None:
    faults_client = MagicMock()

    with pytest.raises(EscalatedError):
        dispatch_with_fallback(
            feature_id="F5",
            correlation_id="01NOFASTPATHARG",
            slow_path=MagicMock(side_effect=RuntimeError("slow path down")),
            faults_client=faults_client,
        )
