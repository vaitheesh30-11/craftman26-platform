# ADR 0028 — agents phase-09: F8 SLR Guardian scope

Status: accepted
Date: 2026-07-31

## Context

`agents/docs/phase-09-slr-guardian.txt` is F8's spec: a Bedrock Agent
(`SlrGuardian`, Haiku 3.5) plus two tool Lambdas (`slr_scan`,
`slr_db_refresh`) that scan a proposed SCP against a curated database of
every AWS Service-Linked Role's required IAM actions and return a
SLR-safe version of the SCP. Same shape of gap as agents phase-02 (ADR
0015): the algorithmic core is buildable and testable offline (moto-mocked
DynamoDB/IAM read APIs, pure Python condition-merge/impact-classification
logic, Pydantic v2 contracts); only CDK wiring and the eval runner need
infrastructure this repo hasn't built yet.

Three scoping decisions were made building this phase, plus one real
cross-module bug fixed along the way.

## Decision

- **CDK wiring for `SlrGuardian`'s `CfnAgent` and its two Lambdas is
  deferred, not built in this phase**, for the identical reason ADR 0015
  gave for F1: `aws-infra/functions/layers/*` are still empty
  `.gitkeep` placeholders, so no specialist's Lambda can be packaged with
  its dependencies yet. `tools/f8/scan.py` and `tools/f8/refresh.py` are
  ready to wire the moment that packaging gap is solved once, for all
  eight specialists.
- **`slr_scan`'s conflict-count threshold (§4 Step 4: "Prefer Strategy A
  unless conflict count > 3") is measured per Deny statement, not per
  whole SCP.** The spec doesn't say which; a proposed SCP with two
  low-conflict Deny statements (2 SLRs each) and no single statement
  exceeding the threshold should get four independent `ArnNotLike`
  patches, not one global `aws:PrincipalIsAWSService` condition that
  weakens every Deny statement in the policy for the sake of one that
  didn't need it. Counting per-statement keeps Strategy B's blast radius
  scoped to the statement that actually needed it, matching §10's own
  framing ("a broad Deny... intersects many SLRs" -- a property of one
  statement's Action list, not the SCP as a whole).
- **`slr_db_refresh` calls `iam:ListPolicies`/`GetPolicy`/`GetPolicyVersion`
  directly via `boto3.client("iam")`, not `cross_account.assume()`.**
  Service-Linked Role policies are AWS-managed and identical across every
  account; this Lambda always runs under the Sentinel platform account's
  own execution role (per §7's IAM Policy section, which grants these
  actions to `slr_db_refresh`'s *own* role, not a cross-account one),
  unlike F1's `passrole_scan`, which reads a specific *member account's*
  IAM state and therefore does need `cross_account.assume()`. Both are the
  same documented exception to "boto3 only through adapters/"
  (agents/README.md §1; no adapter wraps IAM read APIs) that ADR 0015
  established for F1.
- **`enumerate_live_actions`/`refresh_slr_db` take an injectable `scope`
  parameter (default `"AWS"`, matching §4 Step 2's own
  `iam:ListPolicies(Scope="AWS")`)** rather than hardcoding it, because
  moto's IAM mock cannot fabricate real AWS-managed `AWSServiceRoleFor*`
  policies -- it only returns policies actually created in the test, which
  moto reports as `Scope="Local"`. Tests inject `scope="Local"` to
  exercise the identical pagination/name-filtering/`GetPolicyVersion`
  mechanism production uses with `scope="AWS"`, rather than mocking the
  boto3 client itself and testing nothing real.

## Consequences

1. §9 "Detects every conflict in the 8-fixture suite" — partially covered:
   `tests/unit/f8/test_scan.py` exercises 5 of the 8 named SLRs
   (autoscaling, ecs, rds, sagemaker, lambda) across core-action,
   many-SLR-Strategy-B, no-conflict, and size-limit fixtures, scaled down
   per the revised testing policy (same ratio ADR 0015 applied to F1's
   golden set) rather than building all 8 named fixtures individually.
2. §9 "safe_scp is valid JSON matching AWS SCP schema" — met: `evaluate_scp`
   only ever adds/merges `Condition` blocks onto existing Deny statements;
   `test_scan.py::test_core_action_conflict_is_critical_and_gets_
   strategy_a_condition` asserts no new `Allow` statement is ever
   introduced.
3. §9 "Weekly refresh completes < 60s and updates db_version if change" —
   db_version-increment-on-change is verified
   (`test_refresh.py::test_refresh_bumps_db_version_only_when_a_row_
   actually_changed`); the 60s latency bound is deferred, same as ADR
   0015's item 1 (design-bounded, not measured -- no real or
   load-simulated account exists to benchmark against).
4. §8 "Eval: 20 golden turns" — `agents/evals/f8/golden.jsonl` ships 9
   entries covering all five required categories, schema-checked only
   (`tests/unit/test_f8_golden_schema.py`); `iam_sentinel_agents.evals.
   runner` (phase-12) doesn't exist yet and no deployed agent exists to
   run a turn against, identical to ADR 0015's item 4 for F1.
5. CDK deployment of `SlrGuardian` — deferred pending the same
   Lambda dependency-layer packaging decision ADR 0015 flagged; tracked in
   `docs/EXECUTION_STATE.txt` NOTES + BLOCKERS, not silently dropped.

Real bug fixed while building this phase:
`tools/common/event_parser._coerce_typed_value` only special-cased
`integer`/`number`/`boolean`/`array` Bedrock parameter types; an `object`
typed parameter (Bedrock still JSON-encodes it into the same string
`value` field every scalar type uses) fell through to the default branch
and came back as a raw JSON string instead of a parsed dict. F1..F7's
action groups only ever declare scalar parameters, so this path was never
exercised until `slr_scan(proposed_scp: object)` — F8 is the first tool
parameter typed `object`. Fixed by folding `object` into the same
`json.loads` branch `array` already used, with a regression test in
`tests/unit/test_event_parser.py::test_object_typed_property_is_json_
decoded`.
