# ADR 0033 — agents phase-16: cost guardrails scope, adapters phase-01 reuse, deferred infra

Status: accepted
Date: 2026-07-31

## Context

`agents/docs/phase-16-cost-guardrails.txt` lists eight deliverables: an
in-process cost meter, a pre/mid-invocation budget gate, a `SentinelBudget`
DDB table, CloudWatch composite alarms + AWS Budgets, a weekly cost-report
Lambda, hot-swappable SSM caps, circuit breakers, and a cost-aware model
router. Three of these already exist, built during **adapters phase-01**
and already merged to `main` before this sprint step started:

1. `adapters/src/iam_sentinel_adapters/cost_meter.py`'s `CostMeter` --
   in-process spend accounting emitted as EMF metrics AND written to
   `SentinelBudget` (the exact deliverable §2 names first), with
   `record`/`projected`/`check_budget` already SSM-cap-driven and cached.
2. The mid-invocation Bedrock gate (§5 step 3): `BedrockProvider` and
   `GrokProvider` already call `cost_meter.check_budget(...)` before every
   `InvokeAgent`/`InvokeModel`/`Retrieve` and `cost_meter.record(...)`
   after, using the response's real `usage` block. Building this again
   under this phase's name would duplicate adapters phase-01's own
   ownership and test suite.
3. `adapters/src/iam_sentinel_adapters/circuit_breaker.py`'s
   `BreakerAccessor` -- the exact closed → open → half_open → closed state
   machine §5 step 5 describes, backed by `SentinelBreakers`, already unit
   tested against a stubbed clock (this phase's own §7 test plan item).
4. A binary cost-aware model router (`adapters/llm/model_router.py`) --
   Haiku below 70% of cap unless Sonnet is explicitly requested, Haiku
   forced above 70%. Phase-16 §5 step 8 wants a third tier in between.

What was missing is real `agents`-module orchestration work these
adapters-phase-01 primitives had no reason to build themselves, since
Prime (the caller) didn't exist yet when phase-01 shipped:

- The **pre-invocation gate** (§5 step 2) -- nothing calls
  `check_startable`-shaped logic before `PrimeSupervisor.ask` reaches the
  provider. Phase-01's gate is entirely mid-invocation.
- The **per-principal-per-day cap** (§3.2) -- `CostMeter`'s DDB schema
  (`PK=correlation_id`) has no query path for "this principal's spend
  today" at all.
- **Attribution on the DDB row itself** (§5 step 7: "every SpendSample
  tagged with feature_id/principal/mode") -- `CostMeter.record` already
  took these as keyword arguments for the EMF metric dimensions but never
  persisted them to the DDB `Item`, so a weekly report reading
  `SentinelBudget` directly had nothing to group by.
- The **weekly cost report Lambda** itself (§2, §5 step 7).
- The **tool-invocation runaway cap** (§3.1, §8's "100 calls; halted at 30"
  acceptance criterion) -- no counter existed for this at all.

## Decision

Scope this phase to the agents-module orchestration layer plus the minimal,
additive adapters-module extensions the orchestration layer needs, without
touching adapters phase-01's own call sites or test contracts:

1. **`adapters/src/iam_sentinel_adapters/cost_meter.py`** (additive only):
   - `SpendKind` gains `BEDROCK_DOLLARS`, `ATHENA_DOLLARS`,
     `TOOL_INVOCATIONS`, `PRINCIPAL_DAILY_DOLLARS` -- four new members, zero
     renames. `PRINCIPAL_DAILY_DOLLARS` is deliberately distinct from
     `BEDROCK_DOLLARS`: `check_budget`'s cap lookup is keyed by `kind`
     alone (one SSM parameter per kind), and the $1.00 per-correlation cap
     and $50/day per-principal cap are genuinely different caps for the
     same dollar unit.
   - `record()` now persists `feature_id`/`principal`/`mode` to the DDB
     `Item` (previously EMF-dimension-only). `samples(correlation_id)`
     added as the read path.
2. **`adapters/src/iam_sentinel_adapters/llm/model_router.py`**: `pick_model`
   gains the three-tier logic §5 step 8 specifies (< 25% honor
   `request_hint`; 25-70% downgrade only if the caller passes
   `downgrade_ok=True`; > 70% force Haiku) behind a new `downgrade_ok: bool
   = False` parameter. Every one of phase-01's six original parametrized
   test cases passes unmodified -- the default preserves the exact
   original binary behavior.
3. **`agents/src/iam_sentinel_agents/contracts/budget.py`**: `SpendSample`,
   `BudgetSnapshot`, `CircuitBreakerState` matching §4's interface
   contracts verbatim, plus `WeeklyCostReport` for the report Lambda's
   output shape.
4. **`agents/src/iam_sentinel_agents/tools/common/budget_gate.py`**: the
   pre-invocation gate (§5 step 2). `check_startable` checks both open
   circuit breakers (`bedrock`, `athena`) and both dollar caps
   (per-correlation, per-principal-daily) before a turn is allowed to
   start; `check_tool_invocation_cap`/`record_tool_invocation` implement
   the runaway-agent counter. The per-principal-daily ledger reuses
   `CostMeter`'s existing `correlation_id` partition key via a synthetic
   key (`daily#<principal>#<date>`) rather than adding a new DDB table or
   GSI -- see "Consequences" below for why the real GSI is deferred.
5. **`agents/src/iam_sentinel_agents/prime/supervisor.py`**: `PrimeSupervisor`
   takes optional `cost_meter`/`breaker`/`mode` constructor arguments
   (default `None`/`"slow_single"`). When both are provided, `ask()` calls
   `check_startable` before `invoke_agent` and catches
   `BudgetExceededError`/`CircuitOpenError`, answering
   `verdict=INCONCLUSIVE` per §5 step 3's rule (extended here to
   `CircuitOpenError` for the same reason). Defaulting to `None` is
   deliberate: a `PrimeSupervisor` built without them (every pre-phase-16
   call site, including this module's own pre-existing tests) skips the
   gate entirely instead of silently constructing a real `CostMeter()`/
   `BreakerAccessor()` that would reach for actual DynamoDB the moment
   `ask()` runs.
6. **`agents/src/iam_sentinel_agents/tools/common/cost_report.py`**: the
   weekly report Lambda (§2, §5 step 7), following `tools/f8/refresh.py`'s
   "plain EventBridge-scheduled handler, no `sentinel_handler` envelope"
   pattern -- a cross-feature cost rollup has no single `FeatureID` to tag
   it with. Pure aggregation functions (`top_principals`,
   `cost_per_feature`, `cost_per_finding`, `fast_slow_split`,
   `shadow_overhead`) operate on already-scanned DDB rows, mirroring F6's
   `report.py` fetch/compute split. The publish path writes to
   `cost/{year}-W{week}.json`, the exact key shape
   `adapters/s3/reports.py::ReportsClient._prefix_for_kind` already expects
   (that module's own docstring literally names this Lambda as the writer
   it is waiting on) and that `adapters/tests/unit/test_reports_client.py`
   already exercises end-to-end against.
7. **`agents/evals/cost_guardrails/golden.jsonl`**: 7 golden cases (>5)
   covering all three budget layers, the circuit breaker, both model-router
   tiers, and weekly-report attribution, each cross-referenced to a real
   unit test rather than the phase-12 eval runner.

## Consequences

Deferred -- tracked here, not silently skipped -- because they need either
a real AWS dev account/CDK stack or a schema migration this phase's scope
doesn't include:

1. **The `SentinelBudget` GSI a true per-principal-per-day query would
   need.** The synthetic `daily#<principal>#<date>` key under the existing
   `correlation_id` partition key works for cap enforcement (`check_budget`
   still does a `Query` on one partition key) but means the weekly report's
   `scan_all_samples` cannot filter server-side by principal or day --
   it scans the whole table and buckets in Python. Acceptable at weekly
   batch frequency; a real GSI (`principal` + `date` as a composite sort
   key) is `aws-infra` CDK work with no paired sprint step yet, same shape
   of gap ADR 0009 flagged for the Athena workgroup mismatch.
2. **CloudWatch composite alarms, AWS Budgets integration, and the
   anomaly-detection → SNS `SentinelCostAnomaly` → PagerDuty pipeline**
   (§5 step 6, §8's "anomaly alarm fires within 15 minutes" criterion).
   These are pure CDK/console resources with no code this repo owns to
   write against them yet; no `aws-infra` sprint step currently pairs with
   this one.
3. **The Athena scan-cost gate's `EXPLAIN`/`LIMIT 0` estimator and the
   `consent_large_scan=true` trusted-input flag** (§5 step 4). `athena_
   scan_bytes`/`athena_dollars` accounting already exists (adapters
   phase-01's `CostMeter` + this phase's new `ATHENA_DOLLARS` kind), but
   the pre-query estimator itself is Athena-adapter work with its own
   `EXPLAIN`-vs-`LIMIT 0` design tradeoff the spec itself calls "rough" --
   scoped out to avoid guessing at an unverified API shape, the same
   caution phase-10's ADR 0010 applied to the KB Retrieve trace shape.
4. **§8's four acceptance criteria that need a deployed platform**:
   "every Bedrock call is metered before and after" and "every Athena
   query is estimated before start and hard-checked after" are
   code-complete per adapters phase-01 (Bedrock half) and deferred per
   item 3 above (Athena half); "weekly cost report generated on schedule
   for 4 consecutive weeks" and "cost anomaly alarm fires within 15
   minutes" both need a deployed Lambda/EventBridge schedule and cannot be
   verified without a real AWS account (same deferred-live-check pattern as
   ADR 0001/0002/0003/0004/0010).
5. **SSM parameter provisioning itself** (`/sentinel/budget/*`,
   `/sentinel/pricing/*`) -- the code reads these via `CostMeter`'s
   existing SSM-backed cap lookup; actually creating the parameters in a
   real account is deployment, not code.
