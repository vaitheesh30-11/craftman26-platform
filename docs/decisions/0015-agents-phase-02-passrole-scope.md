# ADR 0015 — agents phase-02: F1 PassRole Cartographer scope

Status: accepted
Date: 2026-07-31

## Context

`agents/docs/phase-02-passrole-cartographer.txt` is F1's spec: a Bedrock
Agent (`PassRoleCartographer`, Haiku 3.5) plus two tool Lambdas
(`passrole_scan`, `passrole_graph`) that enumerate `iam:PassRole` grants in
a target account and compute the maximum privilege reachable in ≤2 hops.
Everything the spec's own algorithm needs is buildable and testable
offline (moto-mocked IAM read APIs, pure Python graph/severity logic,
Pydantic v2 contracts) — same shape of gap as adapters phase-05 (ADR 0006)
and aws-infra phase-08 (ADR 0014): the code is real, only a handful of
downstream integration points need a live AWS account, a deployed Prime,
or infrastructure this repo hasn't built yet.

Four scoping decisions were made building this phase, plus one real
cross-module bug fixed along the way.

## Decision

- **CDK wiring for `PassRoleCartographer`'s `CfnAgent` and its two action-
  group Lambdas is deferred, not built in this phase.** `bedrock_stack.py`'s
  `new_agent()`/`associate_collaborator()` factories (ADR 0012) are ready
  to call, but an action group's `AgentActionGroupProperty` needs a real
  Lambda ARN, and `passrole_scan`/`passrole_graph` depend on `networkx` and
  `pydantic` — neither of which any prior phase has actually packaged into
  a Lambda: `aws-infra/functions/layers/{boto3,powertools}/python/` are
  both still empty `.gitkeep` placeholders across all 16 prior phases (see
  `lambda_stack.py`'s own `_build_layer`). This is a pre-existing, repo-
  wide dependency-packaging gap, not something new to F1 — inventing a
  one-off bundling hack for F1 alone (e.g. ad hoc `BundlingOptions` docker
  packaging) would design that decision under this phase's time box
  instead of deliberately, for one specialist, when eight more (Wave 6)
  will need the identical mechanism. The Python code this phase delivers
  (`tools/f1/scan.py`, `tools/f1/graph.py`) is ready to wire in the moment
  a phase solves Lambda dependency-layer packaging generally.
- **`passrole_graph` calls boto3 IAM read APIs, contradicting the spec's
  own one-line tool-contract summary** ("Pure computation on the payload;
  no AWS calls" — §3.2) **in favor of its algorithmic Step 2** ("For each
  reached role, evaluate that role's attached policies for the
  CRITICAL/HIGH/MEDIUM/LOW rubric" — §4). No `PassRoleEdge` field carries
  the *target* role's own policy content (only the policy that grants the
  PassRole *to* it), so accurate severity classification — the entire
  point of §9's acceptance criteria ("CRITICAL findings publish to SNS and
  reach Security Hub as ASFF") — is unattainable from edge data alone.
  `graph.build_blast_paths` resolves this by assuming into the same
  account (`edges[0].from_principal`'s account) via `cross_account.assume`
  and classifying each reachable role through the identical bounded,
  cached read surface `passrole_scan` already uses. Both tools accept an
  injected `iam_client`/`session` for tests, so neither this deviation nor
  the graph algorithm needs a real AWS account to verify.
- **Per-day scan idempotency (§3.2: "Idempotent per `(account_id,
  principal_arn, day_bucket)`") is not implemented as a caching layer.**
  `adapters.ddb.idempotency.IdempotencyClient` (used here) is a claim-once
  primitive (per its own docstring: "does not memoize/replay a handler's
  return value, only the claim itself") built for Prime's post-turn
  processing (phase-01), not a result cache — and Prime's post-turn
  already makes finding *emission* idempotent per `correlation_id` before
  any DDB/SNS/Security-Hub side effect runs (`prime/post_turn.py`).
  Re-running `passrole_scan` itself is side-effect-free (a read scan), so
  repeat-same-day calls are wasteful, not incorrect. A true day-bucket
  result cache needs a new `SentinelPolicies`-shaped table client, which
  ADR 0006 already established as "add on-demand per consumer" — deferred
  here on the same terms.
- **The golden eval set (`agents/evals/f1/golden.jsonl`) is schema-verified
  only, not run.** `iam_sentinel_agents.evals.runner` is a phase-12
  deliverable (`docs/EXECUTION_PLAN.txt` §6, `agents/docs/
  phase-12-observability-evals.txt`) and doesn't exist yet, and no F1
  Bedrock Agent is deployed to run a turn against (see the first bullet).
  Ten entries (scaled down from the spec's 25, per the revised testing
  policy — same ratio adapters phase-11's 24-payload corpus used against
  its 200-payload spec) cover all five required categories (obvious-yes,
  obvious-no, tricky, adversarial-input, latency-sensitive) and are
  schema-checked by `tests/unit/test_f1_golden_schema.py`. The ≥0.95
  accuracy acceptance criterion cannot be scored until phase-12's runner
  and a deployed agent both exist.
- **§9's "500-principal account under 60s" acceptance criterion is a
  design property, not a measured benchmark.** `scan_account` bounds
  concurrent `GetPolicyVersion` fetches to 10 workers (§10's own
  mitigation) and caches each unique managed-policy ARN once per scan;
  provisioning 500 moto-mocked IAM principals to time it would make the
  unit suite slow for a number moto's mock latency can't represent anyway
  (moto has no network round-trip to approximate). Deferred until a real
  or load-simulated account exists to benchmark against.

## Consequences

1. §9 "500-principal scan <60s" — deferred; design-bounded, not measured
   (see NOTES + BLOCKERS).
2. §9 "wildcard resolver correctness on all four fixtures" — met; verified
   by `tests/unit/f1/test_pipeline_fixtures.py` against all four fixtures.
3. §9 "CRITICAL findings publish to SNS and reach Security Hub as ASFF" —
   code-complete at the point findings would flow (Prime's post-turn
   already does this for every specialist's `Finding`s uniformly); not
   independently re-verified for F1 specifically since that path was
   already covered by agents phase-01's own test suite.
4. §9 "Eval verdict accuracy ≥95%" — deferred; no runner exists (phase-12)
   and no deployed agent exists (this ADR's first bullet).
5. §9 "Zero prompt-injection follow-throughs" — the existing 24-payload
   corpus (agents phase-11, ADR 0004) already carries 2 F1-scoped entries
   (`role_name_as_instruction`, `direct_instruction_override`); not
   expanded further per the revised testing policy, and still deferred
   end-to-end (no deployed Prime/Guardrail) per ADR 0004's own note.
6. CDK deployment of `PassRoleCartographer` — deferred pending a Lambda
   dependency-layer packaging decision that belongs to all eight
   specialists, not just F1; tracked in `docs/EXECUTION_STATE.txt` NOTES +
   BLOCKERS, not silently dropped.

Real bug fixed while building this phase: `tools/common/cross_account.
_assume_role_once` never passed `Tags`/`TransitiveTagKeys` to
`sts:AssumeRole`, so `aws:PrincipalTag/Feature` — the condition key
aws-infra ADR 0014 gates F2/F3/F5's mutating cross-account actions on —
never actually existed at runtime. Fixed in this phase (F1 is the first
caller of `cross_account.assume()` to actually ship), with a regression
test (`test_assume_sets_feature_principal_tag_as_a_session_tag`).
