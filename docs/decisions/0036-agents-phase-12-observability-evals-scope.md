# ADR 0036 — agents phase-12: observability + evals scope, and the
XAI_API_KEY blocker that closes (and reopens) every prior phase's deferral

Status: accepted
Date: 2026-07-31

## Context

`agents/docs/phase-12-observability-evals.txt` lists five categories of
deliverable: Powertools/X-Ray runtime config, CloudWatch dashboards +
metric-filter alarms, the eval harness (`evals/runner.py`, golden datasets,
`evals/judges.py`), a nightly GitHub Actions workflow, and per-alarm
runbooks. Two of these are already delivered by earlier phases that
anticipated this one's numbering:

- `tools/common/runtime.py`'s `sentinel_handler` decorator already owns
  Powertools Logger/Tracer/Metrics setup, the structured `tool_completed`
  log line (§4), and per-invocation metric emission — built incrementally
  across every specialist phase (F1..F8) as each Lambda needed it, not
  held back for this phase.
- Every specialist phase's own ADR (0015 F1, 0025 F3, 0026 F2, 0027 F4,
  0024 F7, 0030 F5, 0031 F6, 0028 F8) already named "phase-12's eval
  runner doesn't exist yet" as the reason its golden-set accuracy criterion
  was schema-verified only, never run.

That second point is why this phase is unusually high-leverage: building
`iam_sentinel_agents.evals.runner` for real retroactively unblocks every
one of those eight deferrals simultaneously, the moment `XAI_API_KEY` is
provisioned. It does not retroactively run them today — the key still
isn't provisioned (ADR 0007, unchanged since adapters phase-01) — but it
removes the *other* blocker (the harness not existing) that every one of
those ADRs also cited.

## Decision

Built for real, matching what the golden sets on disk actually contain
(agents/evals/{f1..f8}/golden.jsonl, shipped incrementally by phases
02/03/05/25/24/30/31/28 — NOT phase-12 §6.2's aspirational
`expected.specialist`/`must_mention_actions` shape, which no existing
golden file uses):

1. `agents/src/iam_sentinel_agents/evals/types.py` — `EvalCase` (models
   the real on-disk schema), `JudgeVerdict`, `ScoreBreakdown`,
   `PhaseReport`.
2. `agents/src/iam_sentinel_agents/evals/runner.py` — `LiveInvoker` calls
   the real specialist prompt (`prompts/specialists/*.txt`) or Prime's
   (`prompts/prime_supervisor.txt`) through the existing `LLMProvider`
   adapter (`invoke_model` with `response_schema=SpecialistVerdict`,
   Grok locally / Bedrock in AWS — adapters phase-01, ADR 0007), then
   scores routing/verdict/citation deterministically against the parsed,
   already-validated contract (Pydantic's own field validators — e.g.
   `Finding.aws_doc_citation`'s manifest check — are the ground truth, not
   a second LLM opinion). Only the grounding dimension calls a judge.
3. `agents/src/iam_sentinel_agents/evals/judges.py` — the exact §6.5 judge
   prompt/JSON contract, plus `judge_grounding_majority` (§11's
   "retry-3-and-vote" flakiness mitigation).
4. `agents/evals/prime/golden.jsonl` — a 5-case starter set (single-
   specialist routing, multi-specialist fan-out, out-of-domain rejection,
   a prompt-injection probe, and an unconfirmed-kill-request escalation
   path exercising F5's REJECT → Prime's `compose_status` REJECTED
   precedence). Not the spec's 25 — same "reduced corpus, revised testing
   policy" precedent every prior phase's golden set already set (f2: 10,
   f3/f4: 7, f6: 9, f7: 8, f8: 9 — none of the eight shipped sets hit 25
   either; phase-12 is the first phase positioned to backfill all of them
   to 25 once it has a real pass/fail signal to size against, not before).
5. `--phase 01`..`--phase 09` sprint-numbering map (`PHASE_TO_GOLDEN`),
   matching this repo's own build order (ADR 0013 phase-01=Prime, ADR
   0015 phase-02=F1, ... ADR 0028 phase-09=F8) — not feature-ID order.

Explicitly scoped OUT of this pass, tracked below rather than silently
skipped:

- CloudWatch dashboard JSON + CDK wiring (§7), metric-filter alarms (§3),
  and `.github/workflows/agents-evals.yml`. `tools/common/runtime.py`
  already emits every metric §3's catalog needs (`SentinelInvocation`,
  `ColdStart`, per-tool dimensions); wiring those into CDK-managed
  dashboards and alarms is aws-infra's stack ownership, not agents/'s —
  building CDK JSON here without aws-infra's `BedrockStack`/
  `SecurityStack` context to wire it into would be unreviewable, unwired
  scaffolding. Follow-up: whichever phase next touches aws-infra's stacks
  should add `aws-infra/dashboards/*.json` per §7 and the SNS-alarm
  wiring per §3, both now unblocked since the metrics they filter on
  already exist in `runtime.py`.
- Runbooks (§8) — four short markdown files with no dependency on this
  phase's code; deferred as pure documentation debt, not a code gap.
- X-Ray subsegment naming audit for every AWS API call (§5) — no live AWS
  account exists to inspect a real trace against (same "no dev account"
  pattern as ADR 0001/0002/0003).

## The XAI_API_KEY blocker

`XAI_API_KEY` is still unprovisioned (`adapters/settings.py`'s
`xai_api_key` defaults to `""`; no `.env.local` exists anywhere in this
repo, confirmed by search). `runner.main()` checks this explicitly before
invoking the provider and prints `NOT RUN -- XAI_API_KEY unprovisioned`
rather than attempting a network call that would either hang or fail with
an opaque `requests` exception — this is a real, pre-existing blocker
(tracked in `docs/EXECUTION_STATE.txt` NOTES + BLOCKERS since ADR 0007),
not a harness failure.

Consequence: `uv run python -m iam_sentinel_agents.evals.runner --phase NN`
was NOT run for real against any phase in this session. Every phase's
weighted eval score remains "not run, XAI_API_KEY unprovisioned" — no
number was invented for any of F1-F8 or Prime.

Once the key lands, re-run is a one-line command per phase and closes the
loop opened by ADR 0015 (F1), 0026 (F2), 0025 (F3), 0027 (F4), 0030 (F5),
0031 (F6), 0024 (F7), 0028 (F8), and this ADR (Prime) simultaneously:

```
SENTINEL_LLM_PROVIDER=grok uv run python -m iam_sentinel_agents.evals.runner --phase 01   # Prime
SENTINEL_LLM_PROVIDER=grok uv run python -m iam_sentinel_agents.evals.runner --phase 02   # F1
...
SENTINEL_LLM_PROVIDER=grok uv run python -m iam_sentinel_agents.evals.runner --phase 09   # F8
```

## Consequences

- The harness itself is real and unit-tested deterministically (fixture
  invoker + stub provider, per phase-12 §9's own test plan) — what is
  deferred is exclusively the live LLM call, gated on the same
  pre-existing credential gap every prior phase already named.
- `agents/evals/prime/golden.jsonl`'s 5 cases should grow toward the
  spec's 25 once a first real run against Grok gives a baseline to expand
  from; expanding blind, with no pass/fail signal, would risk writing 20
  more cases that encode the same untested assumption.
- Dashboards/alarms/nightly-CI/runbooks are real follow-up work for
  whichever phase next has aws-infra `BedrockStack`/`SecurityStack`
  context loaded — tracked in `docs/EXECUTION_STATE.txt`, not silently
  dropped.
