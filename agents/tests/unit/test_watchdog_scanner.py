"""`watchdog.scanner.scan_stuck_sessions` (agents phase-17 §6). §12 Test
Plan: "fixture with 3 stuck sessions; verify synthetic DecisionRecords
written; verify SNS emitted; verify cleanup." §13 acceptance: "Watchdog
rescues stuck sessions in < 90s p95" -- not independently benchmarked here
(no deployed Lambda to time), but the threshold/no-activity logic that
determines "stuck" is exercised directly.
"""

from __future__ import annotations

from datetime import datetime, timedelta, UTC
from unittest.mock import MagicMock

import pytest

from iam_sentinel_agents.watchdog.scanner import scan_stuck_sessions, watchdog_scanner

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 7, 31, 12, 0, 0, tzinfo=UTC)


def _in_flight_row(
    *, correlation_id: str, feature_id: str, minutes_ago: int, status: str = "in_progress"
) -> dict[str, object]:
    return {
        "correlation_id": correlation_id,
        "feature_id": feature_id,
        "principal": "arn:aws:iam::111111111111:role/auditor",
        "status": status,
        "started_at": (_NOW - timedelta(minutes=minutes_ago)).isoformat(),
    }


def _clients(rows: list[dict[str, object]]) -> dict[str, MagicMock]:
    in_flight = MagicMock()
    in_flight.list_all.return_value = rows
    return {
        "decisions_in_flight_client": in_flight,
        "decisions_client": MagicMock(),
        "faults_client": MagicMock(),
        "sns_client": MagicMock(),
        "dlq_client": MagicMock(),
    }


def test_rescues_three_stuck_sessions_and_leaves_a_fresh_one_alone() -> None:
    rows = [
        _in_flight_row(correlation_id="01STUCK1", feature_id="F1", minutes_ago=10),
        _in_flight_row(correlation_id="01STUCK2", feature_id="F2", minutes_ago=6),
        _in_flight_row(correlation_id="01STUCK3", feature_id="F5", minutes_ago=20),
        _in_flight_row(correlation_id="01FRESH", feature_id="F1", minutes_ago=1),
    ]
    clients = _clients(rows)

    result = scan_stuck_sessions(
        now=_NOW,
        cleanup_fn=lambda: {"cleaned": [], "extended": []},
        **clients,
    )

    assert set(result.rescued_correlation_ids) == {"01STUCK1", "01STUCK2", "01STUCK3"}
    assert clients["decisions_client"].put.call_count == 3
    assert clients["sns_client"].publish_critical_finding.call_count == 3
    assert clients["decisions_in_flight_client"].complete.call_count == 3

    written = [call.args[0] for call in clients["decisions_client"].put.call_args_list]
    assert all(row["status"] == "ESCALATED" for row in written)
    assert all(row["reason"] == "watchdog: session stuck" for row in written)


def test_f3_f4_get_the_extended_10_minute_threshold() -> None:
    # 7 minutes stuck is past the default 5-minute threshold but under F3/
    # F4's extended 10-minute one (§10 risk mitigation).
    rows = [_in_flight_row(correlation_id="01LONGRUN", feature_id="F3", minutes_ago=7)]
    clients = _clients(rows)

    result = scan_stuck_sessions(
        now=_NOW, cleanup_fn=lambda: {"cleaned": [], "extended": []}, **clients
    )

    assert result.rescued_correlation_ids == []
    clients["decisions_client"].put.assert_not_called()


def test_active_trace_within_no_activity_window_is_not_rescued() -> None:
    rows = [_in_flight_row(correlation_id="01ACTIVE", feature_id="F1", minutes_ago=10)]
    clients = _clients(rows)
    recent_activity = _NOW - timedelta(minutes=1)

    result = scan_stuck_sessions(
        now=_NOW,
        cleanup_fn=lambda: {"cleaned": [], "extended": []},
        last_activity_at=lambda _cid: recent_activity,
        **clients,
    )

    assert result.rescued_correlation_ids == []


def test_non_in_progress_rows_are_ignored() -> None:
    rows = [
        _in_flight_row(correlation_id="01DONE", feature_id="F1", minutes_ago=10, status="complete")
    ]
    clients = _clients(rows)

    result = scan_stuck_sessions(
        now=_NOW, cleanup_fn=lambda: {"cleaned": [], "extended": []}, **clients
    )

    assert result.rescued_correlation_ids == []


def test_rows_missing_started_at_are_skipped_defensively() -> None:
    rows = [{"correlation_id": "01BAD", "feature_id": "F1", "status": "in_progress"}]
    clients = _clients(rows)

    result = scan_stuck_sessions(
        now=_NOW, cleanup_fn=lambda: {"cleaned": [], "extended": []}, **clients
    )

    assert result.rescued_correlation_ids == []


def test_session_kill_queue_age_alarm_fires_past_5_minutes() -> None:
    clients = _clients([])
    clients["dlq_client"].get_age_of_oldest_message.return_value = 400

    result = scan_stuck_sessions(
        now=_NOW,
        session_kill_queue_url="https://sqs.us-east-1.amazonaws.com/123/SessionKillQueue.fifo",
        cleanup_fn=lambda: {"cleaned": [], "extended": []},
        **clients,
    )

    assert result.queue_alarmed is True
    assert result.queue_age_seconds == 400
    clients["sns_client"].publish_critical_finding.assert_called_once()


def test_session_kill_queue_age_below_threshold_does_not_alarm() -> None:
    clients = _clients([])
    clients["dlq_client"].get_age_of_oldest_message.return_value = 30

    result = scan_stuck_sessions(
        now=_NOW,
        session_kill_queue_url="https://sqs.us-east-1.amazonaws.com/123/SessionKillQueue.fifo",
        cleanup_fn=lambda: {"cleaned": [], "extended": []},
        **clients,
    )

    assert result.queue_alarmed is False
    clients["sns_client"].publish_critical_finding.assert_not_called()


def test_no_queue_url_configured_skips_the_queue_age_check() -> None:
    clients = _clients([])

    result = scan_stuck_sessions(
        now=_NOW,
        session_kill_queue_url="",
        cleanup_fn=lambda: {"cleaned": [], "extended": []},
        **clients,
    )

    assert result.queue_age_seconds == 0
    clients["dlq_client"].get_age_of_oldest_message.assert_not_called()


def test_cleanup_fn_result_is_surfaced_on_the_watchdog_result() -> None:
    clients = _clients([])
    cleanup_result = {"cleaned": ["role-a"], "extended": ["role-b"]}

    result = scan_stuck_sessions(now=_NOW, cleanup_fn=lambda: cleanup_result, **clients)

    assert result.cleanup_result == cleanup_result


def test_watchdog_scanner_lambda_entrypoint_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    from iam_sentinel_agents.watchdog import scanner as scanner_module
    from iam_sentinel_agents.watchdog.scanner import WatchdogResult

    monkeypatch.setattr(
        scanner_module,
        "scan_stuck_sessions",
        lambda: WatchdogResult(
            rescued_correlation_ids=["01X"],
            queue_alarmed=False,
            queue_age_seconds=0,
            cleanup_result={},
        ),
    )

    output = watchdog_scanner({}, None)

    assert output["rescued_correlation_ids"] == ["01X"]
    assert output["queue_alarmed"] is False
