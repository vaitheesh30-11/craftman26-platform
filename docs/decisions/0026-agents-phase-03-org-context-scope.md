# ADR 0026 — agents phase-03: F2 Org Context Validator scope

Status: accepted
Date: 2026-07-31

## Context

`agents/docs/phase-03-org-context-validator.txt` is F2's spec: a Bedrock
Agent (`OrgContextValidator`, Haiku 3.5) plus two tool Lambdas
(`org_context_scan`, `org_context_suppress`) that fetch active Access
Analyzer findings, classify each against real AWS Organizations data
(`DescribeOrganization`, `ListAccounts`, full OU tree), and archive
confirmed false positives. Same shape of gap as agents phase-02 (ADR 0015):
the classification algorithm and OU-tree walk are fully buildable and
testable offline; only a handful of downstream integration points need a
live AWS account, a deployed Prime, or Access Analyzer's live API surface
(no moto backend exists for it — ADR 0008's precedent).

Four scoping decisions were made building this phase.

## Decision

- **`OrgContextClassification.matched_condition_key`/`matched_condition_value`
  are optional, not the spec's literal required three-value field.** §4
  Step 3's own algorithm has an "Otherwise" branch (no
  `aws:PrincipalOrgId`/`PrincipalAccount`/`PrincipalOrgPaths` condition
  matched) that produces `TRUE_POSITIVE` or `INCONCLUSIVE_UNKNOWN_CONDITION`
  precisely when no condition key matched at all. A required, three-value
  `Literal` field cannot represent "no key matched" without inventing a
  value that was never present in the finding — exactly what the
  specialist prompt's REASONING CONTRACT ("never invent finding_ids or
  org_ids") forbids in spirit for any contract field derived from real AWS
  data. `contracts/org_context.py` makes both fields optional
  (`matched_condition_key: MatchedConditionKey | None = None`,
  `matched_condition_value: str = ""`).
- **The spec's `CheckAccessNotGranted`-based fallback (§4 Step 3
  "Otherwise... call accessanalyzer:CheckAccessNotGranted with the
  condition removed") is implemented as an injectable
  `AccessStillGrantedCheck` callable, not a concrete API call.** That API
  needs the *original resource policy* the finding was generated from (S3
  bucket policy, IAM role trust policy, KMS key policy, SQS queue policy,
  ...) with the matched condition stripped — `GetFinding` does not return
  that policy verbatim, and building a resource-type dispatch to
  independently refetch and edit six-plus policy shapes is a distinct,
  larger unit of work than this phase's time box, with no moto Access
  Analyzer backend to verify it against either way (ADR 0008's precedent
  reapplied). `tools/f2/classify.py`'s default implementation
  (`_default_access_still_granted`) fails closed to `True` ("still grants
  access" → `TRUE_POSITIVE`) — the one outcome the spec's own SAFETY clause
  and §9 acceptance criteria ("Never archives a TRUE_POSITIVE") both treat
  as the safe side to be wrong on. Real resource-policy-aware
  `CheckAccessNotGranted` wiring can replace the injected callable the
  moment a phase builds the per-resource-type policy-refetch dispatch,
  without changing `classify_finding`'s contract.
- **The spec's DDB caching requirement (§4 Step 1: "Persist as JSON in DDB
  `SentinelPolicies` with TTL 15 min") is deferred, not built.** No
  adapters-side client exists for `SentinelPolicies` yet — adapters
  phase-05 (ADR 0006) shipped clients only for
  findings/decisions/faults/idempotency, not the policy cache table, and
  building + testing one against adapters' own toolchain is out of this
  phase's scope (this phase touches `agents/` only, per its own
  assignment). `tools/f2/org_tree.fetch_org_context` takes an
  `OrgContextCache` Protocol injection point instead, ready to wire the
  moment a `PoliciesCacheClient` exists in `adapters/ddb/`; tests exercise
  both the cache-hit and cache-miss/populate paths against a fixture double.
- **CDK wiring of `OrgContextValidator`'s `CfnAgent` and its two action-
  group Lambdas is deferred, not built in this phase** — identical
  Lambda dependency-layer packaging gap as ADR 0015 (§ "CDK wiring... is
  deferred"), unchanged since that phase; nothing new to F2 specifically.

## Consequences

- Any downstream reader (backend, evals runner) of `OrgContextClassification`
  must treat `matched_condition_key is None` as a valid, expected value for
  `TRUE_POSITIVE`/`INCONCLUSIVE_UNKNOWN_CONDITION` rows — not an error.
- A future phase that builds a real resource-policy-aware
  `CheckAccessNotGranted` check should replace
  `classify._default_access_still_granted`, not add a second code path.
- A future phase that builds `adapters/ddb/policies.py` should implement
  `tools.f2.org_tree.OrgContextCache` and wire it as `org_context_scan`'s
  default `cache=` argument.
- Access Analyzer read/write IAM permissions for the aws-infra
  delegated-admin cross-account role (flagged as unspecified in
  `docs/EXECUTION_STATE.txt`'s notes pending F2/F6) are needed by this
  phase's Lambdas per §7's IAM policy — this is an aws-infra change and is
  out of scope here; flagged for whichever phase wires aws-infra phase-08's
  delegated-admin role's Access Analyzer surface.
