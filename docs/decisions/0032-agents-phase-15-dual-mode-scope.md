# ADR 0032 — agents phase-15: dual-mode execution scope

Status: accepted
Date: 2026-07-31

## Context

`agents/docs/phase-15-dual-mode-execution.txt` is this phase's spec: a
`RequestRouter` classifying every inbound request into `fast` (deterministic,
zero LLM tokens), `slow` (full Bedrock Agent reasoning), or `shadow` (both,
compared for divergence), plus deterministic mirrors for F1/F4/F7/F8,
CloudWatch metrics, a weekly divergence report, and a Prime prompt hook.
`backend.services.router_bridge_service.RouterBridgeService` (backend
phase-01, already merged) was built against this phase's not-yet-existing
`functions/router` Lambda contract (`mode="fast"`, `target`, `payload`,
`principal`, `correlation_id` in; `verdict`/`reason`/`findings`/
`remediation` out, or `items`/`next_token` for the one `GET` read) -- that
exact contract, not a redesign of it, is what `agents/src/iam_sentinel_agents/
functions/router.py` implements here.

## Decision

- **Fast-path mirrors were built for F1, F2, F3, F4, F5, F7, F8 (POST) and
  F6 (the one read route) -- a superset of the spec's explicitly-named
  F1/F4/F7/F8.** `RouterBridgeService` already dispatches `mode="fast"` for
  all eight backend REST routes (`/analyze/passrole`, `/analyze/org-context`,
  `/enrich/policy`, `/analyze/scp-impact`, `/emergency/kill-session`,
  `/resolve/scp-collisions`, `/scan/slr-breakage`, `/monitor/shadow-
  violations`) — leaving F2/F3/F6 unimplemented would mean `functions/
  router.py` 500s on three of backend's eight already-committed routes.
  Every mirror composes the same core function its Bedrock-envelope tool
  Lambda already calls (`tools/f2/classify.scan_and_classify`, `tools/f3/
  query.query_data_events`, `tools/f6/report.load_recent_violations` +
  `build_report`) — same "zero LLM tokens, same computation" contract the
  spec's own §2/§6 Step 2 describes for F1/F4/F7/F8, just not named for
  F2/F3/F6 because those specialists' own phases hadn't landed when phase-15
  was scoped.
- **`AmbiguityError` escalation (§6 Step 2) is caught and reported as
  `verdict="ESCALATE"`, not actually re-dispatched to the slow (Bedrock
  Agent) path.** No `bedrock-agent-runtime:InvokeAgent` call is wired into
  `functions/router.py` yet — this is the same "code-complete, deploy
  deferred" gap ADR 0015/0017/0031 already flagged for every specialist's
  CDK wiring (`aws-infra/functions/layers/*` are still `.gitkeep`
  placeholders), plus there is no deployed Bedrock Agent alias for any
  specialist to invoke against even if the Lambda-layer gap were closed.
  `SentinelFastPathEscalations`/`SentinelRouterDecisions` still increment on
  this path (§6 Step 4), so escalation-rate tuning data is real from day
  one; only the physical re-dispatch hop is deferred. Each mirror's own
  ambiguity condition is a concrete, documented heuristic (F1: >1 unfiltered
  principal; F4: an unidentifiable denying statement; F7: >5 collisions; F8:
  `exceeds_size_limit`) rather than a native `ambiguous=true` flag, since
  none of the underlying tool functions (built in earlier phases, before
  this contract existed) emit one.
- **`RequestRouter.classify()` (the full fast/slow/shadow decision tree,
  §4's Router Policy Matrix) is not wired into `functions/router.py`.** Every
  backend REST route already fixes `mode="fast"` and `target` at the
  URL-path level (the policy matrix's own rows for those exact paths), so
  the Lambda backend actually calls today never needs the tree — it only
  ever receives `mode="fast"`. `classify()` is built, unit-tested against 30
  golden cases (`agents/evals/router/golden.jsonl`), and is the natural
  entry point for whichever service ends up fronting `/agent/chat` (backend
  phase-02's WebSocket service is the likely candidate — that phase existed
  before this one and does not itself call `RequestRouter`), but wiring it
  into a live caller is that caller's phase's job, not this one's.
- **`run_shadow` (§6 Step 3, `tools/common/shadow.py`) is built and unit-
  tested (divergence-kind classification against 5 curated "agree" cases and
  `AmbiguityError`-triggering "escalate" cases per §8's test plan) but not
  invoked from `functions/router.py` or any live caller.** It takes the fast
  and slow paths as injected async callables specifically so production can
  wire a real fast-path dispatcher and a Bedrock `InvokeAgent` coroutine in
  later without this module changing — same reasoning as the `classify()`
  deferral above: no live `mode="shadow"` caller exists yet.
- **CloudWatch dashboards, metric-filter alarms, the weekly divergence
  report Lambda (§6 Step 7), the LLM-as-judge triage (§10), and `scripts/
  review_divergence.py` are deferred.** `adapters.ddb.divergence.
  DivergenceClient` (backend phase-04, already merged) is a real, tested DDB
  client with no producer until this phase — `tools/common/shadow.py::
  run_shadow` is that producer now — but the *ops* half (dashboards, SNS
  digest, CLI review workflow) needs the same CDK-wiring precondition
  (`aws-infra` alarm/dashboard constructs, an SNS topic) as every other
  deferred infra piece above, and no engineer exists yet to review a
  divergence backlog against a platform with zero deployed traffic.
- **The router-policy golden set (`agents/evals/router/golden.jsonl`, 30
  entries) is run for real, not schema-checked only** — unlike every other
  feature's `evals/{feature}/golden.jsonl` (schema-only per ADR 0015 §4th
  bullet: no eval runner exists, no deployed Bedrock Agent to score against).
  `RequestRouter.classify()` is pure Python with zero AWS/LLM dependencies,
  so there is no reason to defer running it; `test_router_golden.py`
  asserts `mode`/`dispatch_target`/`matched_policy_rule_id` against every
  entry.

## Consequences

1. `functions/router.py` today only ever receives `mode="fast"` from its one
   real caller (`RouterBridgeService`). The moment a second caller needs
   `mode="slow"`/`"shadow"` (most likely backend phase-02's WebSocket
   service, fronting `/agent/chat`), that caller's own phase should call
   `RequestRouter.classify()` directly rather than route through this
   Lambda's narrower fast-path-only envelope, or this Lambda's event schema
   should grow a `mode` dispatch branch that calls `classify()` +
   `run_shadow` — a schema change, not a logic change, since both already
   exist.
2. §9 "≥ 60% of production requests served on the fast path after 2 weeks
   of tuning" and "zero material disagreements... during a 7-day window"
   are both unmeasurable against zero deployed traffic; deferred pending the
   same CDK-wiring blocker as every other specialist (tracked in
   `docs/EXECUTION_STATE.txt`).
3. `docs/DATA_CONTRACTS.md`'s `SentinelDivergence` table (aws-infra phase-02)
   now has both a reader (backend phase-04's `DivergenceClient.list_recent`)
   and a writer (`run_shadow`) — whoever wires a live `mode="shadow"` caller
   next should use `run_shadow` unmodified rather than write a second
   divergence producer.
4. Prime's prompt (`prompts/prime_supervisor.txt`) gained CORE RULES §8 (the
   router-deference instruction, §6 Step 5) and `PRIME_PROMPT_SHA256` was
   rebumped in the same commit, per `prompts/registry.py`'s own drift-
   detection contract.
