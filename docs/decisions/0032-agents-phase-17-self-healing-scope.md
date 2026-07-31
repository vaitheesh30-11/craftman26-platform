# ADR 0032 — agents phase-17: Self-Healing scope

Status: accepted
Date: 2026-07-31

## Context

`agents/docs/phase-17-self-healing.txt` asks for six deliverables: a
fault-taxonomy-aware retry primitive, a per-specialist fallback dispatcher,
a watchdog Lambda, three repair Lambdas, a CDK drift detector/
auto-remediator, and a DR runbook + game-day script. Two things make this
phase different from every prior specialist phase: (1) it is cross-cutting
infrastructure, not a Bedrock-callable specialist, so the F1-F8 "20 golden
turns run against a deployed agent" shape does not apply; (2) several of
its own building blocks already existed on `main` before this phase started
— `iam_sentinel_adapters.retry` (backend phase-00) already implements the
exact four backoff policies §4 names, `iam_sentinel_adapters.circuit_breaker`
already implements the adapter-fault circuit-breaking §3's `adapter_fault`
row asks for, and `FaultsClient`/`FaultRecord`'s DDB key shape were already
confirmed against `foundation_stack.py` by backend phase-01 (ADR 0018 item
4) specifically so this phase would have a real table to write into. This
phase's job was therefore narrower than its spec's prose suggests: add the
fault-classification layer, the fallback dispatcher, and the three
Lambda-shaped consumers (watchdog/repair/drift) on top of already-real
primitives, not reimplement retry/circuit-breaking from scratch.

## Decisions

- **`tools/common/retry.py` wraps `iam_sentinel_adapters.retry` rather than
  reimplementing backoff.** `Policy.AGGRESSIVE/CAUTIOUS/SINGLE/NONE` with
  their attempt caps and `total_time_cap` already exist and are already
  used by every DDB/SNS/SQS adapter call in this repo. This phase's actual
  addition is `ADAPTER_CALL_SITE_POLICY` (§4's assignment table, keyed by
  call site) and `with_fault_recording`, a decorator that additionally
  writes a `FaultRecord` on retry-then-succeed (sampled 1/100 for
  `transient_throttling`, per §14) and on final exhaustion (raises
  `RetryExhausted`, always written). `RetryExhausted` keeps that exact name
  (`# noqa: N818`) because §14 risk 1 names it verbatim as the exception
  callers must catch.
- **`tools/common/fallback.py` is built against phase-15's documented
  contract, not its implementation.** §5 explicitly routes through "the
  router" (`agents/docs/phase-15-dual-mode-execution.txt`'s
  `router.execute(mode=...)`), a sibling in-flight branch (sprint step 40)
  not on `main` as of this writing. `dispatch_with_fallback(slow_path,
  fast_path)` takes two zero-argument callables rather than importing
  anything from phase-15 — the same "build against the documented contract,
  not the not-yet-landed implementation" precedent ADR 0018 used for
  `RouterBridgeService`. `FALLBACK_SPECS` transcribes §5's table verbatim,
  including F5/F8's `has_fast_path=False`.
- **Watchdog's "check the Bedrock InvokeAgent trace for activity" (§6 Step
  2a) is an injection point (`last_activity_at`), not a real
  `GetTrace`/CloudWatch Logs Insights call.** No specialist Lambda in this
  repo currently emits a per-invocation trace event `GetTrace` could poll,
  and CloudWatch Logs Insights query syntax needs a real log group ARN this
  repo's dev stage doesn't have wired to a settings key yet. Everything
  else in §6 is real: `DecisionsInFlightClient.list_all()` (added on-demand
  to that client, per ADR 0006's precedent — no prior caller needed "every
  in-flight row"), the synthetic `DecisionRecord(status="ESCALATED")`
  write, the SNS publish, `SentinelDecisionsInFlight` cleanup,
  `SessionKillQueue.fifo`'s `ApproximateAgeOfOldestMessage` alarm (added
  `DlqClient.get_age_of_oldest_message`, generalizing that client beyond
  its original single-metric scope), and `SentinelRevocations` nudging
  (reuses `tools.f5.cleanup.run_cleanup` directly rather than
  re-implementing its "extend vs. clean" TTL logic a second time).
- **All three repair Lambdas take an explicit "what do I already have"
  inventory, not a from-scratch build.**
  - `repair/scp_cache_stale.py` is a thin wrapper: F6's own
    `tools.f6.scp_refresh.refresh_scp_cache` already implements "walk root
    + every OU, re-`DescribePolicy`, write into `PoliciesCacheClient`" —
    this repair Lambda calls it and adds the `EvidenceRecord`/`FaultRecord`
    obligations §7's closing line requires that F6's own 15-minute
    scheduled refresh has no reason to emit on its own routine cadence.
  - `repair/corrupted_memory.py`'s episodic path re-derives from
    `DecisionsClient.get_by_correlation_id` (real); its procedural path
    calls a new `MemoryClient.invalidate_procedural` (added on-demand,
    same precedent); its semantic path takes `resync` as a required
    injection point — the semantic syncer is phase-14 Memory Fabric's own
    deliverable (sibling in-flight branch, sprint step 38, not on `main`).
  - `repair/kb_manifest_drift.py`'s `StartIngestionJob` fan-out is real,
    direct boto3 (no adapter wraps this API; same "boto3 directly,
    documented exception" precedent `tools/f6/scp_refresh.py` and
    `tools/f8/refresh.py` already established). Manifest regeneration
    reuses phase-10's own `build_and_publish_manifest` verbatim, but that
    function's required input (`list[QuoteHash]`, the actual corpus) has no
    producer anywhere in this repo: phase-10's `kb_corpus_fetch`/
    `kb_manifest_generate` Lambdas are themselves still-pending
    `PENDING_EVENT_BINDINGS` rows (ADR 0010). `quotes_provider` is
    therefore a required injection point, and the Lambda-envelope wrapper
    `kb_manifest_drift_repair` raises `NotImplementedError` with a pointer
    to call `repair_kb_manifest_drift()` directly until that upstream
    pipeline exists — not silently faked.
- **`drift/detector.py` is tested against a stubbed
  `CloudFormationClient`, not moto.** moto does not model
  `DetectStackDrift`/`DescribeStackDriftDetectionStatus`/
  `DescribeStackResourceDrifts` (same class of gap ADR 0023 already
  documented for Organizations SCP APIs) — the repo's established
  precedent for that gap is an injectable boto3-shaped double, not skipping
  the scenario. §8's "Never auto-remediate: KMS key policy changes;
  Guardrail changes; Break-glass role changes" is matched by a
  case-insensitive substring check against each drifted resource's logical
  id + type (`_NEVER_AUTO_REMEDIATE_LOGICAL_HINTS`), since the spec names
  these by role, not by one literal CloudFormation resource type — an
  IAM::Role named `BreakGlassRole` and a KMS::Key both need to be caught,
  and no single `ResourceType` string covers "the break-glass role."
  `_AUTO_REPAIRABLE_RESOURCE_TYPES` implements only §8's own worked example
  (`AWS::IAM::Policy`/`AWS::IAM::Role` manually edited) — everything else
  not on the never-remediate list defaults to `paged`, the conservative
  choice, rather than guessing at additional auto-repairable patterns the
  spec never named.
- **CDK wiring for `WatchdogSchedule` (the `rate(1 minute)` binding
  `aws-infra`'s `EventStack.PENDING_EVENT_BINDINGS` already reserves for
  this exact phase), the three repair Lambdas' alarm-action triggers, and
  the daily drift-detector schedule are deferred, not built in this
  phase** — identical reasoning to every prior specialist phase's own CDK
  deferral (ADR 0011/0015/0017/0030/0031): `aws-infra/functions/layers/
  {boto3,powertools}/python/` are still empty placeholders, a repo-wide
  Lambda-packaging gap predating this phase. Every function in `watchdog/`,
  `repair/`, and `drift/` is a real, directly-callable, fully-tested Python
  function with a thin Lambda-envelope wrapper already written — CDK only
  needs to point at it once the packaging gap closes.
- **Region failover (§9) is documented, not exercised.** No `us-west-2`
  standby stack, Route 53 health check, or DDB global table exists in this
  repo's CDK yet (aws-infra has only ever synthesized single-region stacks
  through phase-08). `docs/runbooks/disaster-recovery.md` documents the
  failover path and RTO budget verbatim from §9; `agents/scripts/
  gameday_failover.py` is a real, runnable dry-run script that checks
  whatever of §9's real AWS signals already exist in the current account
  (Route 53 health check status, DDB table `ReplicaDescriptions`) and
  reports "not provisioned" for the rest — it does not fabricate a
  standby-region drill against infrastructure that isn't there.

## Consequences

1. §13 "Watchdog rescues stuck sessions in < 90s p95" — not independently
   benchmarked; no deployed `rate(1 minute)` Lambda exists to time against
   a real fleet of stuck sessions. The threshold/no-activity decision logic
   itself is unit-tested directly.
2. §13 "Every retry policy has a fault-injection test" — met;
   `test_self_healing_retry.py` exercises AGGRESSIVE (retry-then-succeed)
   and SINGLE (exhaustion) against stubbed throttle sequences, plus a
   non-retryable short-circuit case.
3. §13 "Drift detector produces zero false positives on a stable dev
   environment over 7 days" — not measurable; no deployed daily schedule
   or 7-day observation window exists yet. The classifier's never-remediate/
   auto-repairable/default-paged decision boundary is unit-tested for all
   three outcomes.
4. §13 "Region failover drill: p95 total RTO ≤ 5 minutes" — deferred in
   full; tracked in `docs/EXECUTION_STATE.txt` NOTES + BLOCKERS alongside
   every other live-AWS-account gap this sprint has already opened.
5. §13 "Every FaultRecord is queryable via a `POST /operations/faults`
   API" — the spec's own wording says POST; the real, already-merged
   endpoint (backend phase-01 §7, ADR 0018 item 4) is `GET
   /operations/faults`. Treated as the spec's typo, not a second endpoint
   to build: `FaultsClient.list_recent`'s `fault_class`/`since` filters
   already match what a read-only query endpoint needs, and every producer
   in this phase writes through the exact `FaultRecord` shape that endpoint
   already displays.
6. `repair_kb_manifest_drift`'s Lambda-envelope wrapper
   (`kb_manifest_drift_repair`) intentionally raises `NotImplementedError`
   rather than shipping a callable-but-wrong handler — re-open once
   phase-10's corpus-fetch pipeline (ADR 0010) lands.
