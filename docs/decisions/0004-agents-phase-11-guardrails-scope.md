# ADR 0004 — agents phase-11: scope to guardrail policy content + corpus

Status: accepted
Date: 2026-07-30

## Context

`agents/docs/phase-11-guardrails-safety.txt` lists six deliverables: the
Guardrail CDK custom resource, the XML fencer, the sanitizer, a Zelkova
adapter, break-glass STS provisioning, and a 200-payload prompt-injection
corpus. Four of those six are already delivered by other, earlier sprint
steps in `docs/EXECUTION_PLAN.txt` §6, which exists specifically to
de-duplicate work across the per-module phase docs (each module's
`phase-NN.txt` was authored independently, assuming its own dependency
chain, before the cross-module sprint order was written):

- XML fencer + sanitizer: `adapters/prompts/` (adapters phase-03, sprint
  step 05 — already done).
- Break-glass STS role + two-signer Step Functions workflow + CloudTrail
  alarm: `aws-infra` `SecurityStack` (aws-infra phase-01, sprint step 04 —
  already done).
- Zelkova adapter (`access-analyzer:CheckNoNewAccess` wrapper): explicitly
  scheduled as its own sprint step (adapters phase-02, sprint step 11,
  Wave 2) — building it now would duplicate that step's ownership and
  skip its own dedicated test plan.

`docs/EXECUTION_STATE.txt`'s sprint-progress line for this step already
names it "Guardrails config content" — the two deliverables genuinely
unique to this phase are the Guardrail's actual policy payload (topics,
content filters, PII regexes, contextual grounding — `aws-infra phase-01`
built only the generic create/update/delete Lambda plumbing, not this
content) and the prompt-injection corpus.

## Decision

Scope this sprint step to:
1. The Guardrail policy content itself, as `aws-infra/config/guardrail_v1.json`
   (topic/content/PII/grounding config from phase-11 §3), wired through an
   extended `GuardrailCustomResource` construct and lifecycle Lambda.
2. `agents/tests/prompt_injection/corpus.jsonl` — reduced from 200 to a
   representative set (per the revised testing policy: focused coverage,
   not exhaustive corpora) covering all 8 categories §6 lists: direct
   override, indirect-via-untrusted-context, role-name-as-instruction,
   base64-encoded override, homoglyph, RTL-override, XML-tag-closure,
   JSON injection.
3. A schema/quality test for the corpus file itself (every entry has the
   required fields, `expected_outcome` is a valid enum value).

## Consequences

- Acceptance criterion "zero payloads in the 200-corpus follow through the
  model" cannot be verified yet — there is no deployed Prime/Guardrail to
  run the corpus against (Prime doesn't exist until agents phase-01,
  sprint step 16, Wave 3; the Guardrail itself isn't deployed until a real
  AWS account exists per ADR 0001). This is the same deferred-live-check
  pattern as ADR 0001/0002/0003: tracked explicitly in
  `docs/EXECUTION_STATE.txt`, not silently skipped.
- The corpus is a living artifact — running it end-to-end against a real
  deployed Guardrail + Prime should happen once both exist, and again
  during agents phase-13 (integration + prompt-injection tests).
