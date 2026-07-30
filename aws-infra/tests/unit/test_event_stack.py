"""Contract checks for EventStack (phase-06 §4): the 4 composite alarms
whose metric/resource already exists on main, and the
`register_event_rule()` / `register_schedule()` substrate + its
`PENDING_EVENT_BINDINGS` table. Every EventBridge rule/schedule targeting
a not-yet-built specialist Lambda is deferred per ADR 0020 -- see that
file for the full accounting.
"""

from __future__ import annotations

from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_sns as sns
from aws_cdk.assertions import Match, Template

from iam_sentinel_infra.app_factory import build_app
from iam_sentinel_infra.stacks.event_stack import PENDING_EVENT_BINDINGS, EventStack


def _event_stack() -> EventStack:
    app = build_app("dev")
    stack = app.node.find_child("SentinelEvent")
    assert isinstance(stack, EventStack)
    return stack


def test_zelkova_violations_alarm_watches_real_emitted_metric() -> None:
    template = Template.from_stack(_event_stack())
    template.has_resource_properties(
        "AWS::CloudWatch::Alarm",
        {
            "Namespace": "IAMSentinel",
            "MetricName": "SentinelZelkovaViolations",
            "Threshold": 0,
            "ComparisonOperator": "GreaterThanThreshold",
            "Period": 60,
        },
    )


def test_guardrail_interventions_alarm_thresholds_at_20_per_hour() -> None:
    template = Template.from_stack(_event_stack())
    template.has_resource_properties(
        "AWS::CloudWatch::Alarm",
        {
            "Namespace": "IAMSentinel",
            "MetricName": "SentinelGuardrailInterventions",
            "Threshold": 20,
            "Period": 3600,
        },
    )


def test_session_kill_dlq_alarm_watches_real_dlq_queue_depth() -> None:
    template = Template.from_stack(_event_stack())
    resources = template.find_resources("AWS::CloudWatch::Alarm")
    matches = [
        props
        for props in resources.values()
        if props["Properties"].get("MetricName") == "ApproximateNumberOfMessagesVisible"
    ]
    assert len(matches) == 1
    assert matches[0]["Properties"]["Threshold"] == 0


def test_bedrock_spend_anomaly_alarm_uses_anomaly_detection_band() -> None:
    template = Template.from_stack(_event_stack())
    template.has_resource_properties(
        "AWS::CloudWatch::Alarm",
        {
            "ComparisonOperator": "LessThanLowerOrGreaterThanUpperThreshold",
            "Metrics": Match.array_with(
                [
                    Match.object_like(
                        {"Expression": Match.string_like_regexp("ANOMALY_DETECTION_BAND.*")}
                    )
                ]
            ),
        },
    )


def test_break_glass_and_drift_alarms_are_not_duplicated_in_event_stack() -> None:
    """Per ADR 0020: both already exist against real resources in earlier
    phases (SecurityStack, CrossAccountStack) -- EventStack must not
    recreate them."""
    template = Template.from_stack(_event_stack())
    resources = template.find_resources("AWS::CloudWatch::Alarm")
    metric_names = {props["Properties"].get("MetricName") for props in resources.values()}
    assert "Invocations" not in metric_names  # BreakGlassAssumptionAlarm's own metric
    # Zelkova, Guardrail, SessionKillDlq, BedrockSpendAnomaly (CfnAlarm synthesizes to the
    # same AWS::CloudWatch::Alarm CFN resource type as the L2 Alarm construct).
    template.resource_count_is("AWS::CloudWatch::Alarm", 4)
    template.resource_count_is("AWS::Events::Rule", 0)  # no rule targets exist yet (ADR 0020)


def test_pending_event_bindings_cover_every_deferred_spec_rule() -> None:
    expected_rule_ids = {
        "GuardDutyF5Trigger",
        "IdCRevokeF5Trigger",
        "MgmtTrailSubscription",
        "SlrDbRefreshSchedule",
        "ShadowGuardReportSchedule",
        "CostReportWeeklySchedule",
        "MemorySemanticSyncerSchedule",
        "ShadowGuardScpRefreshSchedule",
        "WatchdogSchedule",
        "KbIngestTriggerSchedule",
        "KbCorpusFetchSchedule",
        "KbManifestGenerateChain",
    }
    actual_rule_ids = {binding.rule_id for binding in PENDING_EVENT_BINDINGS}
    assert actual_rule_ids == expected_rule_ids
    assert all(binding.owning_phase for binding in PENDING_EVENT_BINDINGS)


def test_register_event_rule_and_register_schedule_produce_real_rules() -> None:
    """Exercises the substrate future owning phases will call -- an SNS
    topic stands in for a real Lambda/Step Functions target."""
    event_stack = _event_stack()
    topic = sns.Topic(event_stack, "FakeTarget")

    event_stack.register_event_rule(
        event_stack,
        "FakeGuardDutyRule",
        event_pattern=events.EventPattern(source=["aws.guardduty"]),
        target=targets.SnsTopic(topic),
        description="test rule",
    )
    event_stack.register_schedule(
        event_stack,
        "FakeSchedule",
        schedule_expression="rate(1 hour)",
        target=targets.SnsTopic(topic),
        description="test schedule",
    )

    template = Template.from_stack(event_stack)
    template.resource_count_is("AWS::Events::Rule", 2)
    template.has_resource_properties(
        "AWS::Events::Rule", {"ScheduleExpression": "rate(1 hour)"}
    )
