# ADR 0002 — aws-infra phase-01: EventBridge management events instead of a new CloudTrail Trail

Status: accepted
Date: 2026-07-30

## Context

`aws-infra/docs/phase-01-security-stack.txt` §6 specifies CloudTrail alarms
built from a CloudWatch Logs metric filter (`SentinelBreakGlassAssumption`)
over a CloudTrail delivery log group, with an alarm at threshold 1 in
5 minutes feeding SNS `SentinelSecurity`.

Building that literally means `SecurityStack` must own a new
`cloudtrail.Trail` resource (plus its log group and S3 delivery bucket) to
guarantee events land somewhere `add_metric_filter` can read. `SYSTEM_STATE.md`
§1 scopes IAM Sentinel as a governance layer over an existing AWS
Organization — it does not describe Sentinel provisioning its own
org-wide or account-wide CloudTrail trail, and doing so here would be a new,
billable, org-governance-relevant resource decided unilaterally inside a
single stack's phase.

AWS delivers CloudTrail management events (including every `AssumeRole`
call) to the default EventBridge event bus automatically, with no Trail
resource required, via the `"AWS API Call via CloudTrail"` detail-type.

## Decision

Replace the CloudTrail Trail + log group + metric filter with an
EventBridge rule matching `source: ["aws.sts"], detail-type: ["AWS API Call
via CloudTrail"], detail.eventName: ["AssumeRole"], detail.requestParameters.roleArn:
[<break-glass role ARN>]`, targeting the `SentinelSecurity` SNS topic
directly. A CloudWatch Alarm on the rule's own `AWS/Events` `Invocations`
metric (dimensioned by rule name) reproduces the "threshold 1 in 5 minutes"
semantics without requiring a new Trail.

## Consequences

- No new CloudTrail Trail is created; if the account instantiating this
  stack does not already have a trail delivering management events (most
  production AWS accounts do, and Organizations trails cover all member
  accounts), this rule will not fire. This must be verified once a real
  dev account exists (tracked alongside ADR 0001's deferred items).
- Detection latency is lower than the log-group/metric-filter path
  (EventBridge delivers management events within seconds; CloudWatch Logs
  delivery from CloudTrail can lag by minutes).
- The "CloudWatch dashboard widget" mentioned in phase-01 §6 test plan is
  deferred to the dashboard-consolidation phases (`aws-infra/dashboards/`);
  it is not listed in phase-01's numbered acceptance criteria.
