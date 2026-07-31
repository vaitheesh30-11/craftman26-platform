# ADR 0031 — agents phase-07: F6 Shadow Guard scope

Status: accepted
Date: 2026-07-31

## Context

`agents/docs/phase-07-shadow-guard.txt` is F6's spec: a Bedrock Agent
(`ShadowGuard`, Haiku 3.5) plus `shadow_guard_ingest` (CloudWatch-Logs-
driven), `shadow_guard_report` (agent-callable), and `shadow_guard_scp_refresh`
(scheduled) Lambdas that continuously evaluate management-account CloudTrail
writes against the org's SCP chain. Two contradictions and one missing
dependency were resolved building this phase, same shape of gap as ADR 0015
(F1) and ADR 0006 (adapters ddb scope).

## Decision

- **The shared SCP evaluation engine phase-07 §4 Step 2 calls
  `scp_engine.evaluate_action` and credits to "phase-05" does not exist.**
  Only agents phase-00 (foundation) and phase-02 (F1) are built on `main`;
  phase-05 (F4 SCP Impact Analyst, `agents/docs/phase-05-scp-impact-
  analyst.txt`), the module's originally-planned author, hasn't landed.
  `agents/src/iam_sentinel_agents/tools/common/scp_engine.py` implements
  phase-05 §4 Step 2's algorithm now, under F6, matching its published
  `evaluate_action(chain, action, resource, principal_tags, principal_arn)
  -> EvaluationResult` signature exactly (not a narrowed F6-only variant) so
  phase-05 can adopt it unmodified. `EvaluationResult` tracks a boolean
  allowed-so-far rather than materializing phase-05's literal "set of all
  actions" `effective_allowed` description -- no AWS API enumerates that
  set, and every real consumer (`BlockedInvocation`, `ShadowViolation`)
  only ever asks "is this one action allowed," which is what
  `evaluate_action` answers per call.
- **The `SentinelPolicies` DDB table (docs/DATA_CONTRACTS.md §9) had no
  client.** ADR 0006 scoped adapters/ddb to 3 representative table clients
  plus "add the remaining 9 on-demand when the specialist ... that
  actually needs it lands" -- F6 is that specialist for `Policies`.
  `adapters/src/iam_sentinel_adapters/ddb/policies.py`'s `PoliciesClient`
  adds one attribute beyond the documented shape (`level`:
  `"root"|"ou"|"account"`) so `get_chain()` can reconstruct an ordered SCP
  chain from a flat DDB query without a second Organizations round-trip --
  additive, non-breaking per §10's own change policy, and no existing
  consumer to drift against.
- **Phase-07 §5's prompt requires citing BOTH AWS quotes on every Finding,
  but `Finding.aws_doc_citation` (docs/DATA_CONTRACTS.md §4) carries
  exactly one `AwsDocCitation` — no list field exists for a second quote.**
  Resolved by making the more specific quote (AWS Organizations: "SCPs
  have no effect on users or roles in the management account.") the
  structured citation, and embedding the second (AWS prescriptive
  guidance) verbatim in `Finding.detail` (`tools/f6/ingest.py:
  violation_to_finding`) so "cite both" is honored in the Finding's actual
  text without a `Finding` schema change that every other feature's
  Findings would also have to absorb.
- **CDK wiring for `ShadowGuard`'s `CfnAgent` and its three Lambdas is
  deferred**, identical reasoning to ADR 0015's first bullet: the Lambda
  dependency-layer packaging gap (`aws-infra/functions/layers/*` still
  `.gitkeep` placeholders) predates and spans all eight specialists, not
  just F6.
- **`shadow_guard_scp_refresh`'s Organizations API calls
  (`ListPoliciesForTarget`, `DescribePolicy` for SCPs) are not covered by a
  moto-backed unit test.** moto's Organizations support does not model SCP
  attachment/`DescribePolicy` content as of this phase's dependency
  versions; `refresh_scp_cache` takes an injected `organizations_client`
  (a plain stub/`unittest.mock` double in tests) rather than `@mock_aws`,
  same injection-point pattern F1's `passrole_graph` established for its
  own boto3 escape hatch.
- **The golden eval set (`agents/evals/f6/golden.jsonl`) is schema-verified
  only, not run** -- identical reasoning to ADR 0015's fourth bullet:
  `iam_sentinel_agents.evals.runner` is a phase-12 deliverable that doesn't
  exist yet, and no F6 Bedrock Agent is deployed. Nine entries cover all
  five required categories (obvious-yes, obvious-no, tricky, adversarial-
  input, latency-sensitive), scaled down from the spec's 20 on the same
  ratio ADR 0015 used against phase-02's 25.

## Consequences

1. `tools/common/scp_engine.py` is now shared infrastructure two phases
   depend on (F6 today, F4 whenever phase-05 lands) — whoever builds
   phase-05 should extend this module in place, not fork a second copy.
2. §9 "Real-time ingestion latency < 5s" and "Weekly report deploys clean
   via `cdk synth`" are both deferred pending the same CDK-wiring blocker
   as every other specialist (tracked in `docs/EXECUTION_STATE.txt`).
3. §9 "Service prefix coverage ≥95% of AWS service catalog" is met by
   `tools/common/service_prefixes.py`'s curated table (~60 services)
   *plus* its unconditional fallback heuristic for anything uncurated —
   the acceptance criterion as literally worded (95% *exact* curated
   coverage) is not independently measured against a live AWS service
   catalog; deferred until `shadow_guard_scp_refresh`'s own "known-
   services registry" mitigation (§10) exists.
4. §9 "Zero false positives on the fixture set" — met; verified by
   `tests/unit/f6/test_shadow_guard_scp_evaluator.py` and
   `tests/unit/f6/test_ingest_pipeline.py` against crafted fixtures
   covering Allow/Deny/NotAction/NotResource/conditioned-Deny/SLR-exception.
5. Merge-time reconciliation (this phase built in the same parallel batch
   as F4/phase-05 and F7/phase-08, each unaware of the others' work):
   (a) this phase's own `tools/common/scp_engine.py` -- built early,
   matching phase-05's own published `evaluate_action`/`LevelPolicies`
   signature exactly, per this ADR's original framing -- collided at merge
   time with F4's now-already-merged `tools/common/scp_policy_evaluator.py`
   (an independently-written but behaviorally equivalent implementation of
   the identical phase-05 §4 Step 2 algorithm). Renamed this phase's copy to
   `tools/common/shadow_guard_scp_evaluator.py` rather than consolidate three
   independent SCP-evaluation modules (this phase's, F4's, and F7's
   `scp_engine.py`) under merge-time pressure -- all three implement
   overlapping but not identical algorithms and reconciling them into one
   shared engine is real, deferred work for whoever next touches any of
   the three. (b) this phase's own `adapters/ddb/policies.py`
   (`PoliciesClient`) collided with F4's already-merged `PoliciesCacheClient`
   for the same `SentinelPolicies` table and key shape -- unlike (a), this
   was a genuine shared-resource conflict (two clients writing different
   attribute shapes to the same DDB item would corrupt each other's cache
   entries), not just a naming collision, so it was properly unified rather
   than renamed: `PoliciesCacheClient` gained `put_policy`/`get_chain`/
   `is_stale` (this phase's needs) while keeping F4's exact `get`/`put`
   signature and return shape unchanged. This phase's own duplicate
   `adapters/tests/unit/test_policies_client.py` and `policies_table`
   conftest fixture were dropped in favor of F4's already-merged, now-
   extended versions. (c) a real bug in this phase's own test fixture was
   found while re-verifying post-merge: `tests/unit/f6/test_scp_refresh.py`'s
   mock `list_organizational_units_for_parent` paginator ignored `ParentId`
   entirely, returning the same OU list for every parent -- causing the
   walk to treat the one fixture OU as a child of itself and duplicate it
   in the cached-levels count. Fixed by scoping the mock's return value to
   `ParentId == root`. (d) a third, smaller collision of the same kind as
   (a): this phase's own `tools/common/service_prefixes.py`
   (`prefix_for`/`is_curated`) collided with F4's already-merged module of
   the same name (`canonicalize_action`/`is_write_action`, a different
   API for a related but not identical purpose -- F4 canonicalizes a full
   `service:Action` string and filters write verbs; this phase only maps
   an `eventSource` hostname to its bare service prefix and tracks curation
   drift). Renamed to `tools/common/shadow_guard_service_map.py`.
