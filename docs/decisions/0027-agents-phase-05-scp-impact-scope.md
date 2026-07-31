# ADR 0027 — agents phase-05: F4 SCP Impact Analyst scope

Status: accepted
Date: 2026-07-31

## Context

`agents/docs/phase-05-scp-impact-analyst.txt` is F4's spec: a Bedrock Agent
(`ScpImpactAnalyst`, Sonnet 3.5) plus three tool Lambdas (`scp_impact_walk_ou`,
`scp_impact_replay_history`, `scp_impact_simulate`) and a shared SCP
evaluation engine (`tools/common/scp_engine.py`) also consumed by F7
(Collision Resolver, phase-08). Same shape of gap as F1's phase-02 (ADR
0015): the algorithmic core is fully buildable and testable offline
(moto-mocked Organizations/Athena, pure-Python engine logic, Pydantic v2
contracts); only CDK wiring and a couple of downstream integration points
need infrastructure this repo hasn't built yet.

Three scoping decisions were made building this phase.

## Decision

- **CDK wiring for `ScpImpactAnalyst`'s `CfnAgent` and its three action-group
  Lambdas is deferred, not built in this phase**, for the identical reason
  ADR 0015 deferred F1's: `aws-infra/functions/layers/{boto3,powertools}/
  python/` are still empty placeholders, so no specialist's Lambdas can be
  packaged yet. The Python code this phase delivers is ready to wire in the
  moment a phase solves Lambda dependency-layer packaging generally.
- **`scp_impact_walk_ou` and `scp_impact_replay_history` never call
  `cross_account.assume()`**, unlike every F1 tool. `organizations:*` read
  APIs (`ListParents`, `ListPoliciesForTarget`, `DescribePolicy`,
  `ListAccountsForParent`, `ListOrganizationalUnitsForParent`) only succeed
  when called with credentials belonging to the organization's management
  account or a registered delegated administrator — there is no
  per-member-account role to assume into for org-wide Organizations data, in
  contrast to IAM/data-plane APIs which are always evaluated inside the
  member account being read. Both tools instead call
  `boto3.client("organizations"/"athena", ...)` directly, relying on their
  own Lambda execution role carrying phase-05 SS7's read policy (granted
  `Resource: "*"`, consistent with this being an org-wide read, not a
  per-account one). `org_client`/`athena_client` are still constructor-level
  injection points (mirroring F1's `session` parameter), so no live AWS
  account is needed to test either tool.
- **Step 6's severity rubric ("CRITICAL: role has >= 1000 calls AND is
  tagged production via `organizations:ListTagsForResource`") cannot be
  implemented inside `scp_impact_simulate`.** That tool's own OpenAPI
  request body (phase-05 SS6: `chain`, `proposed_scp`, `history`, `mode`)
  carries no account id, and neither `scp_impact_walk_ou` nor
  `scp_impact_replay_history`'s response schemas carry account tags either
  — no step in the three-tool pipeline the spec itself defines ever calls
  `ListTagsForResource`, despite SS7 granting the permission for it. This
  mirrors ADR 0015's second bullet (a spec algorithm step whose data
  dependency contradicts its own interface contract). Resolved in the
  rubric's own favor per phase-05 SS10's documented Risk mitigation
  ("production tags missing on accounts... severity falls back to
  call-count-only rubric"): `tools/f4/severity.assign_severity` accepts an
  `is_production_account: bool | None` parameter for forward compatibility
  (a future phase that threads account tags through some other path can
  raise CRITICAL without changing this function's signature) but every
  caller today passes `None`, so CRITICAL is currently unreachable and every
  Finding's severity is HIGH (>=100 calls) or MEDIUM (<100 calls). The
  "ops OU" leg of the HIGH tier has the same data-availability gap (OU
  *names* are never fetched by `walk_ou`, only OU *ids*) and is dropped for
  the same reason — the >=100-calls branch already covers most
  ops-relevant volume.

## Consequences

1. SS9 "Engine passes every canonical SCP example including the ones AWS
   documents incorrectly" — the engine's algorithm is implemented per SS4
   Step 2 exactly (intersect Allow ceilings, subtract Deny, NotAction/
   NotResource inversion, the one exact `aws:PrincipalIsAWSService`+SLR
   condition resolution); the specific canonical-AWS-docs-are-wrong fixture
   corpus (`docs/aws-scp-canonical-examples/`) is not built in this phase —
   deferred, tracked in `docs/EXECUTION_STATE.txt` NOTES + BLOCKERS.
2. SS9 "p95 latency <= 90s for a 5-level, 500k-call history" — deferred;
   design-bounded (bounded sampling at 500k rows, single-pass evaluation
   per historical row) rather than measured, same treatment ADR 0015 gave
   F1's throughput criterion.
3. SS9 "SuggestedExemptions are valid SCP JSON (schema-validated)" — met:
   `tools/f4/simulate._build_exemption` reconstructs the full original
   denying statement (Effect/Action/Resource/Sid) and only adds a Condition,
   rather than emitting a bare Condition fragment, so `statement_to_add` is
   always a complete, schema-valid SCP statement.
4. SS9 "Sampled runs are labeled and reproducible via a recorded sample
   seed" — met: `tools/f4/replay_history.sample_rows` returns
   `(rows, sampled, seed)` and reproduces identically given the same seed.
5. SS9 "Eval verdict accuracy >= 95%" — deferred; no runner exists
   (phase-12) and no deployed agent exists, same as ADR 0015's fourth
   bullet. `agents/evals/f4/golden.jsonl` (7 entries, scaled down from the
   spec's 25 per the revised testing policy) is schema-checked only.
6. CDK deployment of `ScpImpactAnalyst` — deferred pending the same
   Lambda dependency-layer packaging decision ADR 0015 already tracks for
   all eight specialists.
7. `docs/aws-scp-canonical-examples/` golden fixture corpus and the
   IAM-policy-tag severity path (bullet 3 above) are the two items a future
   phase would need to complete SS9 in full.
8. Naming collision found at merge time: the spec names this module
   `scp_engine` and lists F7 (phase-08) as a second consumer, but F7
   merged to main first (built during the same parallel batch as this
   phase) and created its own `tools/common/scp_engine.py` -- a different
   data model (root-to-account intersection/union across OU branches for
   collision detection) built because this phase hadn't landed yet. The
   two are not interchangeable and reconciling them into one true shared
   engine is real work this phase did not attempt (risk of destabilizing
   F7's already-tested collision logic for a merge-time fix). Renamed this
   phase's module to `tools/common/scp_policy_evaluator.py` instead.
   Whoever next touches either F4 or F7's engine should evaluate unifying
   them.
