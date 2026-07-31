# ADR 0033 — agents phase-13: integration & E2E tests — moto/in-process real coverage, live Bedrock dev-alias runs deferred

Status: accepted
Date: 2026-07-31

## Context

`agents/docs/phase-13-integration-tests.txt` asks for: 12 E2E scenarios run
against a deployed Prime agent on a Bedrock dev alias (`bedrock-agent-
runtime:InvokeAgent`, `enableTrace=true`); a 200-payload prompt-injection
corpus sweep; contract round-trips (>= 500 Hypothesis examples/model);
chaos/fault-injection tests; and a CI workflow gating pre-prod promotion.

Three real gaps, consistent with prior ADRs in this codebase rather than
new problems invented for this phase:

**Gap 1 — no dev AWS account exists.** Every earlier agents-phase ADR that
touches Prime (0013, and the F1-F8 specialist-scope ADRs) already tracks
this as open in `docs/EXECUTION_STATE.txt`. Phase-13's own §4 Step 1
acknowledges it too ("Bedrock dev alias points at real Bedrock... uses a
dedicated dev AWS account") without that account existing. Twelve
`InvokeAgent` scenarios against a live SUPERVISOR-mode Prime with all 8
specialists associated cannot be built without one.

**Gap 2 — Prime's specialist routing/fan-out is Bedrock's job, not
Python's (ADR 0013 Gap 2, reaffirmed here).** Several of phase-13's own
scenarios (E-09 multi-specialist orchestration, E-10 Guardrail
intervention, E-11 Zelkova reflection loop, E-12 chaos-driven escalation)
describe behavior that lives in the deployed agent's prompt/model layer:
mapping a caught exception or a set of specialist outputs into an explicit
verdict or a retry decision. That mapping is not a Python function this
repository owns to unit-test in isolation from a real model call.

**Gap 3 — the 24-payload prompt-injection corpus (ADR 0013, phase-11) was
never grown to phase-13's 200.** Expanding it 8x is real, standalone
authoring work (new attack categories, not just more of the same 8) that
this phase's actual deliverable — wiring integration tests across already-
merged modules — does not depend on. Treating it as blocking would import
scope from a different phase's acceptance criteria into this one's.

## Decision

- **Build `agents/tests/e2e/`, `agents/tests/chaos/`, and
  `agents/tests/contract/test_evidence_signature.py` against real
  production code, moto-mocked or precedented test doubles, never a live
  Bedrock call.** Every scenario in the phase-13 §3 table that has a real
  Python code path today (F1-F8 tool functions, `decision_composer`,
  `PrimePostTurnProcessor`, `ZelkovaClient`, `BedrockProvider`'s retry/
  Guardrail-check plumbing, `IdempotencyClient`/`DynamoDbHelper`'s retry
  plumbing) is exercised for real, most of them end-to-end through the
  real `PrimePostTurnProcessor` against moto DDB + S3 + SNS (not
  `MagicMock`, unlike the existing phase-01 unit tests) — genuinely new
  integration coverage, not a restatement of unit tests.
- **For E-09/E-10/E-11/E-12, prove both real halves of the scenario and
  document the un-testable middle honestly** (same pattern ADR 0013
  established for the 9/24 `guardrail_intervened` corpus payloads): the
  real signal-producing code (sanitizer rejection, Guardrail-intervened
  response, Zelkova witness, DDB/Bedrock retry exhaustion) on one side;
  the real, structural `DecisionRecord` outcome `decision_composer` would
  produce once that signal is expressed as a `SpecialistVerdict` on the
  other; never a fabricated Python function standing in for Bedrock's own
  prompt-layer classification.
- **`agents/tests/e2e/runner.py::run_dev_alias` exists as scaffolding, not
  a working implementation.** It raises `DevAliasNotConfiguredError`
  unconditionally in this environment (no `SENTINEL_PRIME_DEV_ALIAS_ID`)
  rather than silently skipping or returning a fabricated pass.
  `.github/workflows/agents-e2e.yml`'s `dev-alias` job calls it exactly
  once, manual-dispatch-only, and is expected to fail until a dev account
  exists — visible failure, not silent green.
- **Do NOT expand the prompt-injection corpus to 200 in this phase.** The
  24-payload corpus (ADR 0013) continues to run for real against Prime's
  sanitizer (`tests/prompt_injection/test_corpus_through_prime.py`);
  growing it to 200 distinct, well-categorized payloads is tracked as
  open, separate authoring work in `docs/EXECUTION_STATE.txt`, not
  silently declared done here.
- **Contract coverage**: reuses the existing `tests/contract/` suite
  (already built in an earlier wave, including hypothesis round-trips) and
  adds `test_evidence_signature.py` for the one named gap phase-13 §3
  Step 3 calls out that didn't already have a dedicated agents-side test
  (KMS-signed evidence verifiability + canonicalization stability, against
  the exact evidence-body shape `PrimePostTurnProcessor.process` builds).

## Consequences

- Acceptance criteria needing a deployed Prime, a live Guardrail, or a
  real dev AWS account remain open, tracked in `docs/EXECUTION_STATE.txt`:
  "12/12 scenarios pass on a clean dev deploy" (11/12 real in-process +
  moto; E-09 through E-12's model-layer half deferred), "200/200
  prompt-injection payloads" (24/24 real, corpus not yet grown to 200),
  "p95 latencies meet phase-12 SLOs across the 12 scenarios" (no deployed
  Prime to measure against).
- `.github/workflows/agents-e2e.yml`'s `unit-integration` job is real and
  runs on every push to a release branch with zero AWS credentials
  required; its `dev-alias` job is manual-dispatch-only and documented as
  not-yet-implemented rather than removed, so the next phase that gets a
  dev account has a named place to wire it in.
- Whoever provisions a dev AWS account must: (1) deploy Prime with all 8
  collaborators associated (ADR 0013's own open item); (2) implement
  `run_dev_alias` for real against `bedrock-agent-runtime:InvokeAgent`;
  (3) inspect a real `enableTrace=true` trace to finally close ADR 0013
  Gap 3, at which point E-09 through E-12 can be re-run against a live
  Prime instead of this phase's structural proof; (4) grow the
  prompt-injection corpus to 200 payloads.
