# ADR 0024 — agents phase-08: F7 Collision Resolver scope

Status: accepted
Date: 2026-07-31

## Context

`agents/docs/phase-08-collision-resolver.txt` is F7's spec: a Bedrock Agent
(`CollisionResolver`, Sonnet 3.5) plus one tool Lambda (`collision_resolve`)
that walks an account's root-to-account SCP chain, computes the effective
policy, and reports collision points (an explicit Allow at one level
overridden by an explicit Deny at another) with a deterministic
plain-English explanation and a minimal fix. Same shape of gap as agents
phase-02 (ADR 0015): the algorithmic core is fully buildable and testable
offline (moto's Organizations mock covers `ListParents`/
`ListPoliciesForTarget`/`DescribePolicy` completely), only a handful of
downstream integration points need infrastructure this repo hasn't built
yet.

Five scoping decisions were made building this phase, one of them forced by
a real spec/contract contradiction (not a routine implementation choice).

## Decision

- **`tools/common/scp_engine.py` is built from scratch in this phase, not
  reused.** §2 states F7 "Reuses `common/scp_engine.py` from phase-05" —
  but F4 (agents phase-05, `docs/DATA_CONTRACTS.md`'s own §8 index:
  `ScpImpactPayload` / `phase-05-scp-impact-analyst.txt`) hasn't shipped on
  `main`; only F1 (agents phase-02) exists so far. Inventing a one-off,
  F7-scoped engine under `tools/f7/` instead would create exactly the wrong
  dependency direction the moment F4's phase runs (F4 would either
  duplicate the engine or import from `tools/f7`, a sibling feature
  package). The engine is built once, correctly, under `tools/common/` —
  the same location the spec's own wording already implies it belongs —
  so F4 imports the identical module when its phase lands. The engine's
  evaluation model (bounded "candidate actions" harvested from the chain's
  own Allow/Deny statements, rather than attempting to enumerate IAM's
  unbounded action namespace) is documented in the module's own docstring.
- **`AwsDocCitation.url`'s pattern (`^https://docs\.aws\.amazon\.com/.+`,
  `contracts/finding.py`) cannot literally be satisfied by F7's own cited
  source.** §1 and the prompt's GAP header both cite "AWS re:Post, AWS
  staff response" — a `repost.aws` URL, not a `docs.aws.amazon.com` one.
  This isn't F7-specific: F6 also cites AWS prescriptive guidance (a third
  domain) per `docs/AWS_GAPS.md`. Loosening the shared `Finding.url` regex
  (or the KB corpus's `docs.aws.amazon.com`-only egress allowlist,
  `phase-10-rag-knowledge-base.txt` §"why domain allowlist") to accommodate
  one feature's citation domain is a cross-cutting contract decision
  affecting all 8 specialists and the KB ingestion pipeline (agents
  phase-10) — not something F7 should decide unilaterally under its own
  time box. F7's golden fixtures and prompt instead cite the AWS
  Organizations User Guide's own SCP-evaluation documentation page (the
  page whose examples the re:Post response says are wrong) as `url`, while
  keeping `quote`/`source` as the literal AWS re:Post staff statement the
  phase doc specifies — `quote` and `source` carry no domain constraint,
  only `url` does. Revisit if/when a KB-ingestion phase decides to widen
  the allowlist.
- **CDK wiring for `CollisionResolver`'s `CfnAgent` and its
  `collision_resolve` action-group Lambda is deferred, not built in this
  phase**, for the identical pre-existing reason ADR 0015 deferred F1's:
  `aws-infra/functions/layers/{boto3,powertools}/python/` are still empty
  placeholders (Lambda dependency-layer packaging is a repo-wide gap, not
  new to F7).
- **The golden eval set (`agents/evals/f7/golden.jsonl`) is schema-verified
  only, not run.** Same as ADR 0015's F1 precedent: `iam_sentinel_agents.
  evals.runner` is a phase-12 deliverable and no F7 Bedrock Agent is
  deployed. Eight entries (scaled down from the spec's 20, matching ADR
  0015's ratio) cover all five required categories and are schema-checked
  by `tests/unit/test_f7_golden_schema.py`.
- **§10's SLR-crosscheck (F8's DB) and §4 Step 5's Athena call-count reuse
  (F4's) are both wired as optional, injectable inputs to
  `tools/f7/severity.compute_collision_severity`, defaulting to "no data
  available."** F8 (phase-09) and F4 (phase-05) haven't shipped either.
  §10 already anticipates the F8 case explicitly ("if F8's DB is empty ...
  degrade CRITICAL to HIGH and note 'SLR DB not yet initialized'") — this
  phase applies that exact mitigation, and extends the identical reasoning
  to the unwired Athena case (not itself named in §10, but the same shape
  of missing dependency): absent real call-count data, severity stays at
  the spec's own stated default, MEDIUM, rather than guessing a volume.
  `ScpCollision` itself carries no severity field, matching §3's contract
  exactly — severity is computed once per Finding-emission, which for F7
  (as for F1) happens at the specialist-prompt/Prime layer this repo
  hasn't wired end-to-end yet.

## Consequences

1. §9 "Effective-policy blob validates against AWS SCP JSON schema" — met
   for the engine's own output shape (`{Version, Statement: [{Sid, Effect,
   Action, Resource}]}`); not checked against a full downloaded AWS JSON
   schema document (none is vendored in this repo).
2. §9 "Every collision has a valid minimal_fix (SCP JSON schema check)" —
   met by `tools/f7/minimal_fix.is_valid_scp_statement`, a structural
   stand-in for a full schema validator (documented in that function's own
   docstring); verified for both fix strategies in
   `tests/unit/f7/test_minimal_fix.py`.
3. §9 "Plain-English template output is deterministic across runs" — met;
   `tools/f7/plain_english.py` is pure string formatting, verified by
   `test_plain_english.py::test_deterministic_across_repeated_calls`.
4. §9 "p95 latency <= 20s for a 5-level chain with 20 SCPs" — not measured;
   no deployed Lambda/Bedrock Agent exists yet to benchmark (same shape of
   deferral as ADR 0015's item on F1's 500-principal criterion).
5. §8 "Golden AWS re:Post example ... verify Sentinel's engine produces the
   correct result AND emits a Finding calling out the doc discrepancy" —
   the engine-correctness half is met (`f7-obvious-yes-01`/`02` golden
   entries plus `test_scp_engine.py::test_classic_collision_root_deny_ou_allow`
   model exactly this scenario); the Finding-emission half is deferred with
   the rest of end-to-end Finding emission (item 4 above / ADR 0015's
   precedent).
6. CDK deployment of `CollisionResolver` — deferred, tracked in
   `docs/EXECUTION_STATE.txt` NOTES + BLOCKERS alongside F1's identical
   entry, not silently dropped.

No cross-module bug was found while building this phase (unlike ADR 0015's
`cross_account.assume()` fix) — F7 does not call `cross_account.assume()` at
all (§7: "No cross-account role needed"; `tools/f7/chain.py`'s own
docstring explains why).
