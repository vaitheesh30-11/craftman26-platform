"""EventBridge rules, scheduled expressions, and CloudWatch alarms (phase-06).

Per ADR 0020, phase-06's spec (`aws-infra/docs/phase-06-event-stack.txt`
§3) wires ~12 EventBridge rules/schedules to specialist Lambdas -- F5
Session Terminator, F6 Shadow Guard, F8 SLR Guardian, the memory fabric's
semantic syncer, cost guardrails' weekly report, self-healing's watchdog,
and the RAG KB ingestion pipeline -- none of which exist yet (Wave 6/8,
sprint steps 27-41, still pending). Following the same division of
ownership `LambdaStack` established in ADR 0011 (each owning phase calls a
shared registration method from its own stack once its target exists),
this stack exposes `register_event_rule()` / `register_schedule()` for
those future phases and documents the full deferred-binding table in
`PENDING_EVENT_BINDINGS` below.

What IS built now, because its target already exists on main:
- The 4 composite health alarms whose metric/resource is already real
  (Zelkova violations, Guardrail interventions, SessionKillQueue DLQ
  depth, Bedrock-spend anomaly). A CloudWatch alarm does not require its
  source metric to already have data points -- see
  `CrossAccountStack._build_drift_schedule_and_alarm`'s
  `CrossAccountDriftAlarm` (aws-infra phase-08) for the same precedent.

What is deliberately NOT rebuilt here (already real, elsewhere):
- `SentinelBreakGlassAssumption > 0` -- `SecurityStack` (phase-01) already
  built it against the real break-glass STS role.
- The `drift_detector` schedule -- `CrossAccountStack` (phase-08) already
  built the equivalent against the real StackSets.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import aws_cdk as cdk
from aws_cdk import Duration, Stack
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_cloudwatch_actions as cloudwatch_actions
from aws_cdk import aws_events as events

if TYPE_CHECKING:
    from constructs import Construct

    from iam_sentinel_infra.config import StageConfig
    from iam_sentinel_infra.stacks.foundation_stack import FoundationStack
    from iam_sentinel_infra.stacks.lambda_stack import LambdaStack

_ALARM_NAMESPACE = "IAMSentinel"


@dataclass(frozen=True)
class PendingEventBinding:
    """One row of phase-06 §3's spec table whose target Lambda/Step
    Functions workflow does not exist yet. `owning_phase` names the
    sprint phase that will call `EventStack.register_event_rule()` /
    `register_schedule()` from its own stack once it lands -- the same
    division of ownership `LambdaStack.new_function()` established
    (ADR 0011). Kept here, in code, rather than only in the ADR, so the
    table can't silently drift from what the spec actually asked for.
    """

    rule_id: str
    kind: Literal["event_pattern", "schedule", "log_subscription"]
    description: str
    owning_phase: str


PENDING_EVENT_BINDINGS: tuple[PendingEventBinding, ...] = (
    PendingEventBinding(
        rule_id="GuardDutyF5Trigger",
        kind="event_pattern",
        description="aws.guardduty UnauthorizedAccess:*/CredentialAccess:*/"
        "Persistence:IAMUser/* -> session_kill_dispatch",
        owning_phase="agents phase-06 (F5 Session Terminator)",
    ),
    PendingEventBinding(
        rule_id="IdCRevokeF5Trigger",
        kind="event_pattern",
        description="aws.sso DeleteAccountAssignment (via CloudTrail) -> "
        "session_kill_dispatch",
        owning_phase="agents phase-06 (F5 Session Terminator)",
    ),
    PendingEventBinding(
        rule_id="MgmtTrailSubscription",
        kind="log_subscription",
        description="Mgmt-account org trail log group -> shadow_guard_ingest",
        owning_phase="agents phase-07 (F6 Shadow Guard)",
    ),
    PendingEventBinding(
        rule_id="SlrDbRefreshSchedule",
        kind="schedule",
        description="cron(0 4 ? * MON *) -> slr_db_refresh",
        owning_phase="agents phase-09 (F8 SLR Guardian)",
    ),
    PendingEventBinding(
        rule_id="ShadowGuardReportSchedule",
        kind="schedule",
        description="cron(0 9 ? * MON *) -> shadow_guard_report",
        owning_phase="agents phase-07 (F6 Shadow Guard)",
    ),
    PendingEventBinding(
        rule_id="CostReportWeeklySchedule",
        kind="schedule",
        description="cron(0 10 ? * MON *) -> cost_report_weekly",
        owning_phase="agents phase-16 (Cost Guardrails)",
    ),
    PendingEventBinding(
        rule_id="MemorySemanticSyncerSchedule",
        kind="schedule",
        description="rate(1 hour) -> memory_semantic_syncer",
        owning_phase="agents phase-14 (Memory Fabric)",
    ),
    PendingEventBinding(
        rule_id="ShadowGuardScpRefreshSchedule",
        kind="schedule",
        description="rate(15 minutes) -> shadow_guard_scp_refresh",
        owning_phase="agents phase-07 (F6 Shadow Guard)",
    ),
    PendingEventBinding(
        rule_id="WatchdogSchedule",
        kind="schedule",
        description="rate(1 minute) -> watchdog",
        owning_phase="agents phase-17 (Self-Healing)",
    ),
    PendingEventBinding(
        rule_id="KbIngestTriggerSchedule",
        kind="schedule",
        description="cron(0 3 * * ? *) -> kb_ingest_trigger",
        owning_phase="agents phase-10 (RAG KB) follow-on -- see ADR 0010",
    ),
    PendingEventBinding(
        rule_id="KbCorpusFetchSchedule",
        kind="schedule",
        description="cron(0 2 ? * SUN *) -> kb_corpus_fetch",
        owning_phase="agents phase-10 (RAG KB) follow-on -- see ADR 0010",
    ),
    PendingEventBinding(
        rule_id="KbManifestGenerateChain",
        kind="event_pattern",
        description="SNS-triggered after kb_corpus_fetch -> kb_manifest_generate",
        owning_phase="agents phase-10 (RAG KB) follow-on -- see ADR 0010",
    ),
)


class EventStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        stage_config: StageConfig,
        lambdas: LambdaStack,
        foundation: FoundationStack,
        env: cdk.Environment | None = None,
    ) -> None:
        super().__init__(scope, construct_id, env=env)
        self.stage_config = stage_config
        self.lambdas = lambdas
        self.foundation = foundation

        self._build_zelkova_violations_alarm()
        self._build_guardrail_interventions_alarm()
        self._build_session_kill_dlq_alarm()
        self._build_bedrock_spend_anomaly_alarm()

    def register_event_rule(
        self,
        scope: Construct,
        construct_id: str,
        *,
        event_pattern: events.EventPattern,
        target: events.IRuleTarget,
        description: str,
    ) -> events.Rule:
        """Called by an owning specialist/cross-cutting phase (see
        `PENDING_EVENT_BINDINGS`) from its own stack once its Lambda/Step
        Functions target exists -- the same division of responsibility as
        `LambdaStack.new_function()` (ADR 0011)."""
        rule = events.Rule(
            scope, construct_id, event_pattern=event_pattern, description=description
        )
        rule.add_target(target)
        return rule

    def register_schedule(
        self,
        scope: Construct,
        construct_id: str,
        *,
        schedule_expression: str,
        target: events.IRuleTarget,
        description: str,
    ) -> events.Rule:
        """Same shape as `register_event_rule()`, for the cron/rate rows in
        `PENDING_EVENT_BINDINGS`."""
        rule = events.Rule(
            scope,
            construct_id,
            schedule=events.Schedule.expression(schedule_expression),
            description=description,
        )
        rule.add_target(target)
        return rule

    def _build_zelkova_violations_alarm(self) -> None:
        """`adapters/.../zelkova/client.py` already emits this EMF metric on
        every Zelkova violation -- a real, already-shipped signal, not a
        speculative one (phase-06 §4)."""
        alarm = cloudwatch.Alarm(
            self,
            "ZelkovaViolationsAlarm",
            metric=cloudwatch.Metric(
                namespace=_ALARM_NAMESPACE,
                metric_name="SentinelZelkovaViolations",
                statistic="Sum",
                period=Duration.minutes(1),
            ),
            threshold=0,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            evaluation_periods=1,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            alarm_description="A Zelkova formal-verification check found a policy violation.",
        )
        alarm.add_alarm_action(
            cloudwatch_actions.SnsAction(self.foundation.topics["SentinelSecurity"])
        )

    def _build_guardrail_interventions_alarm(self) -> None:
        """Per ADR 0020: no code emits this metric yet (`bedrock_provider.py`
        / `grok_provider.py` raise `GuardrailInterventionError` but never
        EMF-count it) -- the alarm is created ahead of its emitting code,
        the same shape as phase-08's `CrossAccountDriftAlarm`."""
        alarm = cloudwatch.Alarm(
            self,
            "GuardrailInterventionsAlarm",
            metric=cloudwatch.Metric(
                namespace=_ALARM_NAMESPACE,
                metric_name="SentinelGuardrailInterventions",
                statistic="Sum",
                period=Duration.hours(1),
            ),
            threshold=20,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            evaluation_periods=1,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            alarm_description="More than 20 Guardrail interventions in an hour.",
        )
        alarm.add_alarm_action(cloudwatch_actions.SnsAction(self.foundation.topics["SentinelOps"]))

    def _build_session_kill_dlq_alarm(self) -> None:
        """`SessionKillQueue.fifo` + its DLQ are real (`FoundationStack`,
        phase-02) -- any depth here means a session-kill dispatch failed
        the queue's `maxReceiveCount` (3) and needs a human."""
        dlq = self.foundation.session_kill_queue.dead_letter_queue
        if dlq is None:  # pragma: no cover - defensive; FoundationStack always sets one.
            raise ValueError("SessionKillQueue has no dead-letter queue configured")
        alarm = dlq.queue.metric_approximate_number_of_messages_visible(
            period=Duration.minutes(5), statistic="Maximum"
        ).create_alarm(
            self,
            "SessionKillDlqDepthAlarm",
            threshold=0,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            evaluation_periods=1,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            alarm_description="SessionKillQueue-DLQ has messages -- a session-kill dispatch "
            "exhausted its 3 delivery attempts.",
        )
        alarm.add_alarm_action(cloudwatch_actions.SnsAction(self.foundation.topics["SentinelOps"]))

    def _build_bedrock_spend_anomaly_alarm(self) -> None:
        """Per ADR 0020: spec names this metric `SentinelBedrockDollars`; no
        code emits it yet (`cost_meter.py` emits per-invocation
        `SentinelSpend{kind}` token/count metrics, not a derived dollar
        figure) -- agents phase-16's `cost_report_weekly` Lambda is the
        expected eventual publisher. CloudWatch anomaly-detection bands
        need the L1 `CfnAlarm` escape hatch, same as
        `SentinelLambda._build_duration_anomaly_alarm`."""
        spend_metric_id = "m1"
        band_id = "ad1"
        cloudwatch.CfnAlarm(
            self,
            "BedrockSpendAnomalyAlarm",
            alarm_description="Bedrock spend ($) is outside its normal anomaly-detection band.",
            comparison_operator="LessThanLowerOrGreaterThanUpperThreshold",
            evaluation_periods=3,
            threshold_metric_id=band_id,
            treat_missing_data="notBreaching",
            metrics=[
                cloudwatch.CfnAlarm.MetricDataQueryProperty(
                    id=spend_metric_id,
                    metric_stat=cloudwatch.CfnAlarm.MetricStatProperty(
                        metric=cloudwatch.CfnAlarm.MetricProperty(
                            namespace=_ALARM_NAMESPACE,
                            metric_name="SentinelBedrockDollars",
                        ),
                        period=3600,
                        stat="Sum",
                    ),
                    return_data=True,
                ),
                cloudwatch.CfnAlarm.MetricDataQueryProperty(
                    id=band_id,
                    expression=f"ANOMALY_DETECTION_BAND({spend_metric_id}, 2)",
                    label="Bedrock spend (expected)",
                ),
            ],
            alarm_actions=[self.foundation.topics["SentinelCostAnomaly"].topic_arn],
        )
