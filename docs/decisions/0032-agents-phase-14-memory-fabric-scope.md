# ADR 0032 — agents phase-14: Memory Fabric scope

Status: accepted
Date: 2026-07-31

## Context

`agents/docs/phase-14-memory-fabric.txt` asks for four memory tiers
(working/episodic/semantic/procedural), a shared `recall`/`remember` tool
surface (`MemoryActions`), a continuous semantic syncer Lambda, a
procedural memoize decorator, and Prime/specialist prompt updates. The DDB
half of episodic/semantic/procedural memory already exists
(`adapters/src/iam_sentinel_adapters/memory/client.py`, built in adapters
phase-05 per ADR 0006), including its own documented deferral of the
OpenSearch Serverless k-NN read path ("the OSS k-NN read half is a
documented interface stub, deferred with the rest of OpenSearch Serverless
verification per ADR 0005"). This phase builds the agents-side tool layer
on top of that adapter, plus everything else phase-14 scopes to `agents/`.

## Decision

- **Working memory (§3.1) has no code to write.** It is entirely
  Bedrock-managed (`memoryConfiguration=SESSION_SUMMARY`); phase-14 §3.1
  itself says "No API surface". Nothing in this phase implements it beyond
  noting the agent-config field it needs at CDK-deploy time (aws-infra
  concern, tracked in `docs/EXECUTION_STATE.txt`, not this repo's `agents/`
  code).
- **Episodic isolation is enforced structurally in `tools/memory/recall.
  py`/`remember.py`, not merely policy-forbidden.** `recall_episodic` has
  no code path that queries a `principal` other than the one the caller
  identifies as `invoking_principal` (extracted from `promptSessionAttributes.
  principal`, added to `ParsedInvocation` in this phase); passing a
  disagreeing `target_principal` raises `MemoryIsolationError` rather than
  silently substituting. `remember_episodic` further checks the record's
  own `principal` field against the invoking principal. Covered by
  `tests/unit/memory/test_recall_remember.py`'s isolation tests
  (phase-14 §7: "attempt to recall episodic memory for principal A while
  invoking as principal B; must fail closed").
- **`remember`'s IAM-policy-layer writer restriction (§4: "only Prime's
  post-turn Lambda writes episodic; only the syncer writes semantic; only
  individual tool Lambdas write procedural") is modeled with a
  `writer_role` defense-in-depth check in `tools/memory/remember.py`, not
  actual IAM policy documents.** The real enforcement boundary is each
  Lambda's scoped execution-role IAM policy — an aws-infra concern, and
  aws-infra's own CDK stacks for these three Lambdas' roles aren't wired
  yet (mirrors ADR 0013/0015's precedent for every other cross-boundary
  IAM policy in this sprint: code-complete against the documented
  contract, live-policy verification deferred to whoever wires the Lambda
  into CDK).
- **The semantic syncer (`tools/memory/semantic_syncer.py`) fully
  implements two of the spec's six entity syncers — accounts
  (`organizations:ListAccounts`) and permission sets (`sso-admin:
  ListPermissionSets`/`DescribePermissionSet`) — and defers the remaining
  four (OUs, roles, service principals, policies) on the same terms ADR
  0006 already established** ("add each on-demand when the specialist...
  that actually needs it lands, rather than guessing its query shape
  now"). Roles are explicitly "enumerated during F1 scans; refreshed
  opportunistically" per spec §3.3 — driven by F1's own pipeline, not this
  syncer. Service principals seed from F8's SLR DB and policies cache
  during F4/F7 walks — each needs that owning phase's already-built client
  shape, not a guessed one. `_sync_one`'s change-detection/emit-changed
  pattern is identical for all six; wiring in the remaining four is
  mechanical once their source client exists.
- **Change detection is computed independently of `MemoryClient.
  upsert_semantic`'s own (coarser) comparison.** The adapters client's
  `_canonical()` helper compares every item field except `entity_kind`/
  `entity_key` — including `synced_at`, which changes on every sync run,
  so it would never actually detect a no-op by itself. The syncer instead
  reads the existing entity's `body_sha256` via `recall_semantic` and
  compares only that before writing, giving the correct "no write on
  unchanged body" semantics phase-14 §7's test plan requires without
  touching adapters phase-05's already-merged file.
- **`EntityChanged` is emitted via a direct `boto3.client("events")` call
  inside the syncer Lambda**, following the same one-off-client convention
  `tools/f5/dispatch.py` already uses for `sso-admin` (no adapters-level
  EventBridge client exists yet; inventing one for a single `put_events`
  call would be premature relative to phase-14's own scope).
- **The vector-recall golden set (`agents/evals/memory/golden.jsonl`, 20
  curated similar/distinct query pairs per §7) is schema-verified only, not
  run**, for the same two reasons ADR 0015 (F1) and ADR 0010 (RAG KB) both
  already give: `iam_sentinel_agents.evals.runner` (phase-12) doesn't
  exist yet, and the `sentinel-episodic-vector` OpenSearch Serverless
  collection this eval is meant to exercise doesn't exist either (deferred
  per ADR 0005/0006). `tests/unit/test_memory_golden_schema.py` checks
  field shape, category coverage, and the similar/distinct expectation
  invariant.
- **`MemoryActions`'s Lambda handler (`tools/memory/actions.py`) does not
  use `tools.common.runtime.sentinel_handler`.** That decorator is
  parameterized by a single `FeatureID` ("F1".."F8") for its metrics
  dimension/log context, but `MemoryActions` is deliberately the one
  action group every specialist (and Prime) shares — there is no single
  owning feature. `actions.py` hand-rolls the same envelope-parsing/
  logging/error-mapping shape with `feature_id="MEMORY"`-equivalent
  service naming instead of widening `FeatureID`'s type for one caller.

## Consequences

1. §8 acceptance "Four tiers deployed and observable via `SentinelMemoryReads/
   Writes` metrics" — code-complete (metrics emitted in `actions.py`);
   "deployed" itself is an aws-infra CDK step this phase doesn't take.
2. §8 "Prime demonstrably reuses a prior decision within 24h" — prompt
   updated (`prime_supervisor.txt` §MEMORY USE); no deployed Prime exists
   to demonstrate it against yet (same gap ADR 0013 already tracks).
3. §8 "Procedural cache hit rate >= 40% on F4/F7 SCP workload" — the
   memoize decorator and its hit/miss/TTL-expire/version-invalidation unit
   tests are in place; the decorator is not yet wired onto `scp_engine.
   compute_effective_policy`/`evaluate_action` themselves (that wiring is
   a one-line `@memoize_procedural(...)` per call site, left for whoever
   next touches F4/F7's engine so this phase doesn't reach into two other
   specialists' already-shipped modules uninvited).
4. §8 "Semantic syncer drift < 1 hour" and "Cross-principal recall fails
   closed with an alarm" — the drift SLA is an EventBridge `rate(1 hour)`
   schedule (aws-infra CDK, not built here); the fail-closed behavior is
   verified by unit test, the CloudWatch alarm on `SentinelMemoryAccessDenied`
   is not wired (aws-infra concern).
5. Vector k-NN recall accuracy (>= 18/20) — deferred; tracked in
   `docs/EXECUTION_STATE.txt`, same status as ADR 0005/0006's OSS
   deferral this phase inherits.
