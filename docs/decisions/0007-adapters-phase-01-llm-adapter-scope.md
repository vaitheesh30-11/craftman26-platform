# ADR 0007 — adapters phase-01: LLM adapter scope and provider split

Status: accepted
Date: 2026-07-30

## Context

`adapters/docs/phase-01-bedrock-adapter.txt` predates the Grok/Bedrock
provider split; `docs/EXECUTION_PLAN.txt` §2 supersedes it: "when phase-01
executes, the coder MUST build both providers and route via
`SENTINEL_LLM_PROVIDER`." `XAI_API_KEY` is not provisioned locally
(tracked in `docs/EXECUTION_STATE.txt` NOTES + BLOCKERS since this sprint
step was first planned).

## Decision

Build a shared `LLMProvider` Protocol (`invoke_agent`, `invoke_agent_stream`,
`invoke_model`, `retrieve`) with two implementations:

- `BedrockProvider` — real `bedrock-agent-runtime`/`bedrock-runtime` calls
  per phase-01 §3-4: budget gate, circuit breaker, Guardrail-intervention
  detection via `stopReason`, cost-sample emission, `Policy.AGGRESSIVE`
  retry on throttling.
- `GrokProvider` — xAI's OpenAI-compatible chat-completions endpoint via
  `requests` (new dependency; stdlib `urllib` was used for the Lambda
  handlers earlier in this project specifically to avoid needing a Lambda
  layer — that constraint doesn't apply here, this is a regular adapters
  import). Multi-agent collaboration is emulated in-process: `invoke_agent`
  routes directly to the named specialist's system prompt via a single
  chat-completion call, with no real Supervisor→Collaborator hop.
  Guardrail intervention is emulated by a local structural validator
  (`output_validator.py`'s forged-content checks + the sanitizer's
  forbidden-pattern list) rather than Bedrock's own Guardrail.

Both providers are built and unit-tested against mocked HTTP/boto3 calls —
`XAI_API_KEY` still isn't provisioned, so no real xAI call is made or
tested, matching the same deferred-live-check pattern as every ADR since
0001.

Streaming (`invoke_agent_stream`) is implemented at a real-but-not-gold-
plated level: chunk iteration with per-chunk Guardrail-intervention
detection, one final cost-sample on stream close. The spec's "partial-
token sample every 500 chunks" mid-stream cadence is not implemented —
premature without a real caller (streaming has no consumer until backend
phase-02, Wave 4) to validate the right cadence against.

## Consequences

Deferred, tracked in `docs/EXECUTION_STATE.txt`:
- "p99 adapter overhead ≤ 30ms vs raw boto3" — needs a real benchmark
  against live Bedrock, not mocked calls.
- The 20-payload prompt-injection-in-`messages` output-validator suite is
  reduced to a representative set (same revised-testing-policy pattern as
  every prior phase's corpus/property-test scope cut).
- Real xAI calls (`XAI_API_KEY` still unset) — re-run once the key is
  provisioned, before Grok is used for real local dev/evals.
