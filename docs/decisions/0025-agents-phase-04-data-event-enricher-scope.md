# ADR 0025 — agents phase-04: F3 Data Event Enricher scope

Status: accepted
Date: 2026-07-31

## Context

`agents/docs/phase-04-data-event-enricher.txt` is F3's spec: a Bedrock
Agent (`DataEventEnricher`, Sonnet 3.5) plus three tool Lambdas
(`data_event_ensure_logging`, `data_event_query`, `data_event_merge`) that
query CloudTrail S3 data events via Athena, merge them with Access
Analyzer's `StartPolicyGeneration` output, and emit a least-privilege
policy artifact scoped to real prefixes. Same shape of gap as F1 (ADR
0015): the algorithmic core is buildable and testable offline (moto-mocked
CloudTrail, an injected Athena-client double, pure Python merge/
consolidation logic, Pydantic v2 contracts); only a handful of downstream
integration points need a live AWS account, a deployed org trail, or
infrastructure this repo hasn't built yet.

Two scoping decisions were forced by a genuine ambiguity in the spec
itself, plus the usual set of "needs a real account" deferrals ADR 0015
and ADR 0009 already established the pattern for.

## Decision

- **Prefix consolidation (§4 Step 4) resolves to exactly one string per
  usage group, not a set of scopes.** `S3DataEventUsage.consolidated_prefix`
  (§3's own contract) is a single `Optional[str]` field per (action,
  bucket) pair, but the underlying CloudTrail data for that pair is a flat
  list of concrete object keys, and §4's two explicit thresholds ("> 5
  distinct child paths under a prefix", "> 20 distinct root-level paths")
  read as rules for *when* to widen scope across possibly-many subtrees —
  not as a specification for collapsing multiple disjoint subtrees into
  one string. `tools/f3/consolidate.py` resolves this in favor of the
  contract shape: it always computes the single longest common directory
  prefix across every observed key for that (action, bucket) pair and
  collapses everything past that point into one `prefix/*` (or the bare
  key itself, if only one key was ever observed). Root-level fanout over
  20 still collapses to `*` with a `bucket_wide_warning=True` return value
  (§4 rule 4's own "per-Finding warning") rather than raising — a
  data-quality signal, not a fatal error, matching `tools/f1/graph.py`'s
  existing precedent for degraded-but-valid results.
- **`data_event_query`'s Athena SQL is built by string interpolation, not
  literal `?` bind parameters.** §4 Step 3's query template uses `?`
  placeholders, but `athena:StartQueryExecution` has no bind-parameter API
  reachable through boto3 — Athena's only parameterized-query mechanism
  (prepared statements via `CREATE STATEMENT`) is a different, heavier API
  shape the spec doesn't otherwise reference. `tools/f3/query.py` escapes
  the one untrusted-shaped input (`role_arn`, via SQL single-quote
  doubling) and interpolates it directly; every other substituted value
  (`_DATABASE`, `_TABLE`, the action-name list, the zero-padded year/month
  integers) is a module constant or a formatted integer, never caller-
  controlled free text.
- **Workgroup name**: `sentinel`, per aws-infra ADR 0009's own reconciliation
  note ("agents phase-04's `sentinel-f3` should be reconciled to `sentinel`
  when agents phase-04 lands") — `tools/f3/query.py` uses the reconciled
  name, not this phase doc's original `sentinel-f3` literal.
- **`base_policy_generate` (§4 Step 5) and the Zelkova pre-check (§4 Step 7)
  are runtime helpers (`tools/f3/policy_generation.py`), not Bedrock action-
  group tools.** §3's "Tool contracts" section lists only
  `data_event_ensure_logging`/`data_event_query`/`data_event_merge`; the
  specialist prompt's WORKFLOW step 3 itself says `StartPolicyGeneration`
  is called "via a base_policy_generate helper wired through the runtime",
  the same shape as F1's `graph.build_blast_payload` (ADR 0015). Both
  helpers are built directly on `iam_sentinel_adapters.zelkova.ZelkovaClient`
  (adapters phase-02) rather than reinventing
  StartPolicyGeneration/GetGeneratedPolicy/CheckNoNewAccess retry/breaker/
  evidence/cost-meter behavior that adapter already owns.
- **CDK wiring for `DataEventEnricher`'s `CfnAgent` and its three action-
  group Lambdas is deferred**, for the identical pre-existing Lambda
  dependency-layer packaging gap ADR 0015 already named for F1 (still
  unresolved as of this phase; `aws-infra/functions/layers/{boto3,
  powertools}/python/` are still empty placeholders).
- **The golden eval set (`agents/evals/f3/golden.jsonl`) is schema-verified
  only, not run**, and scaled to 7 entries (from the spec's 25) covering
  all five required categories — same deferral as ADR 0015's F1 golden set,
  for the same reason (`iam_sentinel_agents.evals.runner` doesn't exist
  until phase-12, and no F3 Bedrock Agent is deployed to run a turn
  against).
- **Athena integration testing uses an injected fake client, not moto's
  Athena backend.** Moto's Athena mock accepts
  `StartQueryExecution`/`GetQueryExecution` call shapes but has no real SQL
  engine behind them — `GetQueryResults` always returns an empty result
  set regardless of the query string, so it cannot exercise the
  action/bucket/prefix grouping logic this phase's tests need to cover. A
  minimal hand-written fake (three methods:
  `start_query_execution`/`get_query_execution`/`get_paginator`) is injected
  through the same `athena_client=` parameter production skips in favor of
  `cross_account.assume()` — this is the practical reading of §8's own
  "moto's Athena mock plus a fixture Parquet result set" given moto's
  actual behavior.

## Consequences

1. §9 "Merged policy always ≤ 6,144 bytes OR `truncated=true` and no
   attach" — met; `tools/f3/merge.py` collapses to `base_policy` alone
   (dropping every new statement) whenever either the byte cap or the
   wildcard-safety check would otherwise be violated.
2. §9 "No `s3:*` or `Resource:"*"` in any emitted policy" — met;
   `merge.py`'s `_has_forbidden_wildcard` check runs over the full merged
   statement list before any artifact is returned.
3. §9 "Zelkova PASS on every non-truncated merged policy" — code-complete
   (`tools/f3/policy_generation.zelkova_precheck`); not independently
   re-verified end-to-end since no deployed agent exists to run a full
   turn (same gap as items 4-5 below).
4. §9 "Athena query cost per invocation ≤ $0.50 at 100 GB scanned" and
   "End-to-end latency ≤ 90s p95" — deferred; both need a real Athena
   workgroup against real trail data, tracked in
   `docs/EXECUTION_STATE.txt` NOTES + BLOCKERS, not silently dropped.
5. Eval verdict accuracy / prompt-injection follow-through criteria — same
   deferral shape as ADR 0015 items 4-5.
6. CDK deployment of `DataEventEnricher` — deferred pending the same
   Lambda dependency-layer packaging decision named in ADR 0015's item 6.
