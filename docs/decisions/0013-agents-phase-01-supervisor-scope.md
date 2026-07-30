# ADR 0013 — agents phase-01: Sentinel Prime scope — orchestration code + prompt + post-turn processing, not the trace-parsing boundary or per-collaborator wiring

Status: accepted
Date: 2026-07-31

## Context

`agents/docs/phase-01-supervisor-agent.txt` §2 lists 8 deliverables mixing
two modules: the CDK construct/aliases/Guardrail-and-KB attachment (§2
items 1, 6-7; `aws-infra`) and the prompt/post-turn Lambda/action-group
(§2 items 2-5, 8; `agents`). ADR 0012 (aws-infra phase-05) already
anticipated this split explicitly: "Sentinel Prime... is built by agents
phase-01 (sprint step 16)... calling `new_agent()` with its own
instruction text." Three real gaps surfaced while implementing this
phase, each needing its own scoping call.

**Gap 1 — 2 of the 9 DDB table clients ADR 0006 deferred are real
dependencies of this phase, not the next one.** The spec's post-turn
Lambda (§3.2-3.3) requires DDB writes to `SentinelDecisions` (PK
`principal`, SK `decided_at`) and a `SentinelIdempotency` claim keyed by
`correlation_id` (§4 step 3) — both explicitly named in ADR 0006's
deferred-table list, both genuinely needed now rather than "when a
specialist lands."

**Gap 2 — Prime's own specialist routing is not agents/'s code to write.**
Bedrock's `agentCollaboration=SUPERVISOR` mode performs specialist
fan-out/routing server-side, inside the deployed foundation model, driven
by the prompt's own COLLABORATOR DIRECTORY and ROUTING HEURISTICS text
(phase-01 §5, core rule 3: "invoke them in PARALLEL using the
collaborator_invocation tool"). There is no Python routing function to
call in production — `iam_sentinel_adapters.llm.types.LLMProvider.
invoke_agent` already exists specifically for the resulting
already-orchestrated `InvokeAgent` call (adapters phase-01). Treating
"routing" as agents/-side logic to build and unit-test would duplicate
Bedrock's own behavior with no real caller.

**Gap 3 — the post-turn trigger and trace shape are unverified, exactly
as the spec itself flags.** §4 step 3 reads: "implemented as a
self-invoked action-group placeholder if Bedrock trace stream is not
enough — verify against `bedrock-agent-runtime:InvokeAgent`
`enableTrace=true` output before shipping." No dev account exists to make
that real call and inspect the actual trace envelope shape Bedrock
returns for a SUPERVISOR-mode multi-agent turn.

## Decision

- **Build the 2 missing DDB clients** (`DecisionsClient`,
  `IdempotencyClient`) plus a small `SnsClient` (the IAM policy in §6
  explicitly scopes `sns:Publish` to `SentinelCriticalFindings`), all
  following ADR 0006's `DynamoDbHelper` pattern exactly. This closes part
  of ADR 0006's deferred list ahead of the F1 phase that ADR nominally
  assigned it to, because Prime's own post-turn processing is the actual
  first consumer.
- **Build `agents/src/iam_sentinel_agents/prime/`**: `routing.py` (parses
  the prompt's own ROUTING HEURISTICS table as data, for local testing
  and pre-flight fan-out checks only — never the real routing path, which
  is Bedrock's), `result_parser.py` (the OUTPUT PROTOCOL's
  `PROGRESS:`/`RESULT:` text parser), `decision_composer.py` (the verdict
  → `DecisionRecord.status` rollup, §4 step 3's rules), and
  `post_turn.py` (`PrimePostTurnProcessor`: idempotency claim → compose →
  sign+persist evidence → DDB write → SNS/Security Hub on CRITICAL).
  `PrimePostTurnProcessor.process` is fully built and unit-tested against
  explicit `SpecialistVerdict` inputs.
- **Do NOT wire `PrimePostTurnProcessor` to real Bedrock trace parsing.**
  `PrimeSupervisor.ask()` (the `LLMProvider.invoke_agent` wrapper) sanitizes
  the query, invokes, and parses the RESULT block — but stops there. The
  RESULT block's `findings`/`remediations_proposed` are the model's own
  verbatim echo of specialist output, not structured `SpecialistVerdict`
  objects with `tool_invocations`/Zelkova checks; reconstructing those
  would require guessing at the unverified trace shape Gap 3 describes.
  Guessing wrong risks silently fabricating tool-invocation provenance —
  exactly what `output_validator` and `Finding`'s manifest check exist to
  prevent elsewhere in this codebase. Wiring this up is deferred until a
  deployed Prime's real trace envelope can be inspected.
- **Do NOT implement Python-side specialist routing/fan-out logic as
  Prime's real code path.** `routing.py` exists only as a test/tooling
  aid over the prompt's own heuristics table (Gap 2); it is never called
  by `PrimeSupervisor`.
- **Instantiate Prime's `CfnAgent` in `aws-infra`'s `BedrockStack`**
  (`_build_prime`, calling the phase-05 `new_agent()` factory with
  `agent_collaboration="SUPERVISOR"`, the prompt loaded from
  `agents/src/iam_sentinel_agents/prompts/prime_supervisor.txt`,
  `SESSION_SUMMARY` memory config, and the InvokeCollaborators/
  InvokeModelWithResponseStream policy statements §6 lists) with **zero**
  collaborators associated. `associate_collaborator()`'s own docstring
  anticipates this: "Called once per specialist by whichever phase creates
  Prime... after every specialist it wants to collaborate with already
  exists." None of the 8 specialists exist yet (F1 lands next, sprint
  step 18; F2-F8 land in Wave 6) — associating a collaborator alias that
  doesn't exist isn't buildable, let alone testable.
- **Run the 24-payload prompt-injection corpus for real against Prime's
  actual sanitizer code path** (`agents/tests/prompt_injection/
  test_corpus_through_prime.py`) rather than re-deferring it wholesale.
  15/24 payloads (`sanitizer_reject`) are asserted blocked for real — no
  mock, no live AWS needed. The remaining 9 (`guardrail_intervened`:
  base64/homoglyph/RTL payloads deliberately designed to evade the
  sanitizer's literal-pattern regex) are asserted to correctly NOT be
  caught by the sanitizer alone, proving the deferral is real rather than
  silently re-stamped. Catching those 9 needs a deployed Bedrock Guardrail
  (no dev account) or a real xAI call through `GrokProvider`'s output-side
  structural guardrail (`XAI_API_KEY` still unprovisioned, ADR 0007) —
  both blockers predate this phase and are independent of "does Prime
  exist," which is what was originally blocking this test.

## Consequences

- Acceptance criteria needing a deployed Prime, deployed specialists, a
  live Guardrail, or a real xAI call remain open, tracked in
  `docs/EXECUTION_STATE.txt`, not silently dropped: "Prime agent deployed
  in dev with all 8 collaborators associated," "streaming works end-to-end,"
  "eval harness verdict accuracy ≥ 90%," "p95 latency ≤ 25s," and 9/24 of
  the injection corpus.
- "Post-turn Lambda writes idempotent DecisionRecords" and "KMS-signed
  evidence blob present for every turn" ARE met: `PrimePostTurnProcessor`
  is real, unit-tested code exercising the real `DecisionRecord`/
  `EvidenceRef` contracts and the real idempotency-claim semantics — it
  just isn't yet triggered by a real Bedrock trace event.
- Whoever deploys a dev account and Prime must: (1) inspect a real
  `enableTrace=true` `InvokeAgent` response to confirm the trace shape,
  then wire `PrimeSupervisor`/`PrimePostTurnProcessor` together for real;
  (2) confirm whether EventBridge actually emits a usable
  "Agent Trace Post-turn" event or whether synchronous post-processing
  (this phase's assumption) is the right permanent shape; (3) call
  `associate_collaborator()` once per specialist as F1-F8 land.
