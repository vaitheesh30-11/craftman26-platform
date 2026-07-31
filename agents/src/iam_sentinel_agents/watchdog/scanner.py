"""watchdog/scanner -- stuck-session rescue (agents phase-17 §6).

Runs every 60 seconds via EventBridge (`rate(1 minute)`, see this package's
`__init__.py`). Four duties per §6:

1. Query `SentinelDecisionsInFlight` for `started_at > threshold ago` and
   `status=in_progress`.
2. For each stuck record: if no activity within 3 minutes, emit
   `SentinelStuckSession`, write a synthetic `DecisionRecord(status=
   "ESCALATED", reason="watchdog: session stuck")`, publish SNS, then clean
   up (remove from `SentinelDecisionsInFlight`).
3. Alarm `SessionKillQueue.fifo` if `ApproximateAgeOfOldestMessage` exceeds
   5 minutes.
4. Nudge `SentinelRevocations` cleanup -- reuses `tools.f5.cleanup.
   run_cleanup` directly rather than re-implementing "extend vs. clean"
   TTL logic a second time.

§10 risk mitigation ("F3/F4 get 10-minute thresholds instead of 5,
since watchdog rescues too aggressively will kill long-running
specialists") is `_stuck_threshold`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, UTC
from typing import Any, TYPE_CHECKING

from iam_sentinel_adapters.ddb.decisions import DecisionsClient
from iam_sentinel_adapters.ddb.decisions_in_flight import DecisionsInFlightClient
from iam_sentinel_adapters.ddb.faults import FaultsClient
from iam_sentinel_adapters.settings import settings
from iam_sentinel_adapters.sns.client import SnsClient
from iam_sentinel_adapters.sqs.dlq import DlqClient

from iam_sentinel_agents.ids import new_ulid
from iam_sentinel_agents.tools.common.retry import record_fault
from iam_sentinel_agents.tools.f5.cleanup import run_cleanup

if TYPE_CHECKING:
    from collections.abc import Callable

    from aws_lambda_powertools.utilities.typing import LambdaContext

# §6 duty 1/§10 risk mitigation.
_DEFAULT_STUCK_THRESHOLD = timedelta(minutes=5)
_EXTENDED_STUCK_FEATURES = frozenset({"F3", "F4"})
_EXTENDED_STUCK_THRESHOLD = timedelta(minutes=10)
# §6 duty 2b.
_NO_ACTIVITY_THRESHOLD = timedelta(minutes=3)
# §6 duty 3.
_QUEUE_AGE_ALARM_SECONDS = 300


def _stuck_threshold(feature_id: str) -> timedelta:
    return (
        _EXTENDED_STUCK_THRESHOLD
        if feature_id in _EXTENDED_STUCK_FEATURES
        else _DEFAULT_STUCK_THRESHOLD
    )


def _parse_iso(raw: Any) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


@dataclass(frozen=True)
class WatchdogResult:
    rescued_correlation_ids: list[str] = field(default_factory=list)
    queue_alarmed: bool = False
    queue_age_seconds: int = 0
    cleanup_result: dict[str, Any] = field(default_factory=dict)


def scan_stuck_sessions(
    *,
    now: datetime | None = None,
    decisions_in_flight_client: DecisionsInFlightClient | None = None,
    decisions_client: DecisionsClient | None = None,
    faults_client: FaultsClient | None = None,
    sns_client: SnsClient | None = None,
    dlq_client: DlqClient | None = None,
    session_kill_queue_url: str | None = None,
    last_activity_at: Callable[[str], datetime | None] | None = None,
    cleanup_fn: Callable[[], dict[str, Any]] = run_cleanup,
) -> WatchdogResult:
    resolved_now = now or datetime.now(UTC)
    in_flight = decisions_in_flight_client or DecisionsInFlightClient()
    decisions = decisions_client or DecisionsClient()
    faults = faults_client or FaultsClient()
    sns = sns_client or SnsClient(topic_arn=settings.ops_topic_arn or None)
    activity_checker = last_activity_at or (lambda _correlation_id: None)

    rescued: list[str] = []
    for item in in_flight.list_all():
        if item.get("status") != "in_progress":
            continue

        started_at = _parse_iso(item.get("started_at"))
        if started_at is None:
            continue

        correlation_id = str(item["correlation_id"])
        feature_id = str(item.get("feature_id", ""))
        if resolved_now - started_at < _stuck_threshold(feature_id):
            continue

        last_activity = activity_checker(correlation_id)
        if last_activity is not None and resolved_now - last_activity < _NO_ACTIVITY_THRESHOLD:
            continue

        principal = str(item.get("principal", "unknown"))
        decisions.put(
            {
                "principal": principal,
                "decided_at": resolved_now.isoformat(),
                "decision_id": new_ulid(),
                "correlation_id": correlation_id,
                "feature_id": feature_id,
                "status": "ESCALATED",
                "reason": "watchdog: session stuck",
            }
        )
        record_fault(
            correlation_id=correlation_id,
            fault_class="eventual_consistency",
            origin="watchdog:scanner",
            action_taken="escalated",
            detail=f"session stuck since {started_at.isoformat()}; watchdog rescued it",
            faults_client=faults,
            force_write=True,
        )
        sns.publish_critical_finding(
            subject="SentinelStuckSession",
            message=(
                f"correlation_id={correlation_id} feature_id={feature_id} "
                f"stuck since {started_at.isoformat()}"
            ),
        )
        in_flight.complete(correlation_id)
        rescued.append(correlation_id)

    queue_url = session_kill_queue_url or settings.session_kill_queue_url
    queue_age_seconds = 0
    queue_alarmed = False
    if queue_url:
        dlq = dlq_client or DlqClient()
        queue_age_seconds = dlq.get_age_of_oldest_message(queue_url)
        if queue_age_seconds > _QUEUE_AGE_ALARM_SECONDS:
            queue_alarmed = True
            record_fault(
                correlation_id="watchdog-session-kill-queue",
                fault_class="transient_network",
                origin="watchdog:scanner",
                action_taken="paged",
                detail=f"SessionKillQueue.fifo oldest message age {queue_age_seconds}s > 300s",
                faults_client=faults,
                force_write=True,
            )
            sns.publish_critical_finding(
                subject="SentinelSessionKillQueueStuck",
                message=f"ApproximateAgeOfOldestMessage={queue_age_seconds}s exceeds 5-minute alarm.",
            )

    cleanup_result = cleanup_fn()

    return WatchdogResult(
        rescued_correlation_ids=rescued,
        queue_alarmed=queue_alarmed,
        queue_age_seconds=queue_age_seconds,
        cleanup_result=cleanup_result,
    )


def watchdog_scanner(_event: dict[str, Any], _context: LambdaContext) -> dict[str, Any]:
    """EventBridge `rate(1 minute)` scheduled-rule entrypoint -- no Bedrock
    envelope, matching every other scheduled Lambda in this repo
    (`slr_db_refresh`, `shadow_guard_scp_refresh`, `session_kill_cleanup`).
    """
    result = scan_stuck_sessions()
    return {
        "rescued_correlation_ids": result.rescued_correlation_ids,
        "queue_alarmed": result.queue_alarmed,
        "queue_age_seconds": result.queue_age_seconds,
        "cleanup_result": result.cleanup_result,
    }
