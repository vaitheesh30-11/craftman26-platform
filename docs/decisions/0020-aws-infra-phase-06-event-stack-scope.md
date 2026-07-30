# ADR 0020 — aws-infra phase-06: Event stack scope — reusable substrate + alarms only, not the specialist rule targets

Status: accepted
Date: 2026-07-31

## Context

`aws-infra/docs/phase-06-event-stack.txt` §3 lists ~12 EventBridge rules,
scheduled expressions, and a log-group subscription filter, every one of
which targets a Lambda or Step Functions workflow owned by a sprint phase
that has not landed yet:

- `session_kill_dispatch` — agents phase-06 (F5 Session Terminator, sprint
  step 33, Wave 6).
- `shadow_guard_ingest` / `shadow_guard_report` / `shadow_guard_scp_refresh`
  — agents phase-07 (F6 Shadow Guard, sprint step 27, Wave 6).
- `slr_db_refresh` — agents phase-09 (F8 SLR Guardian, sprint step 30,
  Wave 6).
- `memory_semantic_syncer` — agents phase-14 (Memory Fabric, sprint step
  38, Wave 8).
- `cost_report_weekly` — agents phase-16 (Cost Guardrails, sprint step 39,
  Wave 8).
- `watchdog` — agents phase-17 (Self-Healing, sprint step 41, Wave 8).
- `kb_ingest_trigger` / `kb_corpus_fetch` / `kb_manifest_generate` — agents
  phase-10 (RAG KB) landed only `agents/src/iam_sentinel_agents/
  knowledge_base/manifest_service.py` as pure ingestion/manifest logic
  (per ADR 0010); no Lambda wrapper for it exists in `aws-infra/functions/`.

This is the same shape of gap ADR 0011 (aws-infra phase-04) already named:
the phase doc's rule table assumes consumers this sprint's ordering hasn't
reached. Creating an `events.Rule` with `targets.LambdaFunction(...)`
against a Lambda that doesn't exist isn't possible — there is nothing to
construct a real `IFunction` reference from, and stubbing a fake Lambda
purely to satisfy the wiring would fabricate functionality that doesn't
exist rather than defer it honestly.

Two more findings that also belong here rather than blocking the phase:

- Spec's "Drift detector: `cron(0 6 * * ? *)` → `drift_detector`" is
  already covered by `CrossAccountStack._build_drift_schedule_and_alarm`
  (aws-infra phase-08, `cron(0 5 ? * SAT *)`) against the real
  `SentinelCrossAccountRole`/`SentinelDelegatedAdminAccountRole` StackSets.
  Not duplicated here.
- Spec's `SentinelBreakGlassAssumption > 0` composite alarm is already
  built in `SecurityStack` (aws-infra phase-01) against the real
  break-glass STS role. Not duplicated here.
- Spec names the cost-anomaly metric `SentinelBedrockDollars`; the only
  spend metric any code currently emits is `cost_meter.py`'s
  `SentinelSpend{kind}` (per-invocation token/count EMF metrics, not a
  derived dollar figure). The alarm below watches the spec's literal
  metric name on the assumption agents phase-16's `cost_report_weekly`
  Lambda will be the eventual publisher — the same "alarm ahead of its
  emitting code" shape as phase-08's `CrossAccountDriftAlarm`.
- Spec's `SentinelGuardrailInterventions` metric is also not yet emitted
  anywhere (`GuardrailInterventionError` is raised in
  `adapters/llm/{bedrock,grok}_provider.py` but never EMF-counted) — same
  treatment: the alarm is created now, the emission is adapters' scope to
  add whenever it revisits guardrail telemetry.

## Decision

- **Build the reusable substrate only, mirroring ADR 0011's division of
  ownership**: `EventStack.register_event_rule()` and
  `EventStack.register_schedule()` are the entry points every owning
  specialist/cross-cutting phase calls from its own stack once its target
  Lambda/Step Function exists — the same shape as
  `LambdaStack.new_function()`. `PENDING_EVENT_BINDINGS` in
  `event_stack.py` is the authoritative, code-adjacent table of every rule
  from phase-06 §3 that is still deferred, naming the owning phase for
  each so nothing is silently dropped.
- **Build the 4 composite alarms whose metric/resource already exists on
  main**, because a CloudWatch alarm does not require its source metric to
  already have data points (`treat_missing_data=NOT_BREACHING`; same
  precedent as `CrossAccountDriftAlarm`): `SentinelZelkovaViolations > 0/
  1min` (real metric, emitted by `adapters/zelkova/client.py` today),
  `SentinelGuardrailInterventions > 20/hour`, `SessionKillQueueDLQ depth >
  0` (real queue, built in `FoundationStack` phase-02), and
  `SentinelBedrockDollars` anomaly-detection band.
- **`SentinelBreakGlassAssumption` and the drift-detector schedule are not
  recreated** — both already exist against real resources in earlier
  phases; recreating them here would either collide or drift from the
  real implementation.
- Per-Lambda `Errors > 5/5min` and `Duration` p95 anomaly-detection are
  already attached to every `SentinelLambda` unconditionally (phase-04,
  `sentinel_lambda.py`) — nothing to add per phase-06 §4's first bullet.

## Consequences

Deferred until the owning phases land (tracked in `docs/EXECUTION_STATE.txt`,
not silently dropped):

1. All ~12 event sources/schedules in `PENDING_EVENT_BINDINGS` — each lands
   when its owning phase calls `EventStack.register_event_rule()` /
   `register_schedule()`.
2. "Every schedule fires on time within ±60s" and "Alarms deliver to SNS in
   test" (phase-06 §6 acceptance criteria) — both need a deployed stack on
   a real AWS dev account; none exists.
3. The mgmt-account CloudTrail log-group subscription filter
   (`MgmtTrailSubscription`) additionally needs a real org trail's log
   group ARN from the management account, which this sandbox has never had
   (same class of gap as ADR 0002/0014's cross-account dependencies).
4. `SentinelGuardrailInterventions` / `SentinelBedrockDollars` EMF
   emission — adapters' scope, not aws-infra's; the alarms are ready to
   receive data the moment that lands.
