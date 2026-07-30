# ADR 0005 — aws-infra phase-02: key-attribute convention, table count, OSS bootstrap, deferred criteria

Status: accepted
Date: 2026-07-30

## Context

`aws-infra/docs/phase-02-foundation-stack.txt` delegates the DynamoDB table
inventory to `adapters/docs/phase-05-ddb-adapter.txt` §3, whose table lists
**14** rows (`SentinelFindings` through `SentinelIdempotency`) even though
both phase docs' prose says "13 tables." This ADR provisions all 14 —
under-provisioning to match a miscounted headline is worse than a stale
comment.

The §3 table's `PK`/`SK`/`GSIs` columns use a `#`-joined notation
(`account_id#feature_id`, `severity#detected_at`) that is ambiguous on its
own. Two readings are possible: a single composite-value attribute, or two
separate attributes. `docs/ARCHITECTURE.md` §5 uses the identical notation
for this exact table, and the DDB interface in phase-05 §4
(`query_by_severity(severity, since, limit)`) only makes sense as an
efficient query if the GSI has a genuine partition+sort key pair (exact
match on `severity`, range on `detected_at`) rather than one opaque
composite string.

## Decision

- **Main table PK/SK**: one composite-value attribute per slot, named
  literally as printed (e.g. the attribute `account_id#feature_id` holds
  the string `f"{account_id}#{feature_id}"`) — DynamoDB permits `#` in
  attribute names, and this is the only reading that fits DDB's
  one-partition-key/one-sort-key constraint.
- **GSIs**: the last `#`-segment is the sort key attribute; everything
  before it (which may itself be a `#`-joined composite) is the partition
  key attribute. `severity#detected_at` → PK=`severity`, SK=`detected_at`.
  `feature_id#status#detected_at` → PK=`feature_id#status` (composite),
  SK=`detected_at`.
- **All 14 tables** from the phase-05 inventory are provisioned.
- **OSS index bootstrap** (`functions/oss_index_bootstrap/handler.py`)
  signs its own SigV4 requests with `botocore.auth.SigV4Auth` against the
  collection's REST endpoint rather than depending on the `opensearchpy`
  library — `opensearchpy` isn't available in the base Lambda runtime and
  this repo has no Lambda-layer build pipeline yet; hand-signing with
  botocore (already present in every Python runtime) needs no layer at
  all.
- **SNS "delivery status logging"** (phase-02 §7) is not wired: it
  requires success/failure IAM feedback roles per subscription protocol,
  and phase-02 explicitly defers actual subscriptions to SSM-driven
  runtime configuration — there is nothing to log deliveries for yet.
- **`SentinelSecurity` SNS topic**: phase-02 §2 lists it as one of six
  topics to create, but aws-infra phase-01's `SecurityStack` already
  created it for the break-glass alarm. SNS topic names are unique per
  account+region, so `FoundationStack` references
  `security.security_topic` (now exposed as a public attribute) instead
  of creating a second topic with the same name, which would fail at
  deploy time.

## Consequences

Deferred until a real AWS dev account exists (same pattern as ADR
0001/0002/0003 — tracked in `docs/EXECUTION_STATE.txt`, not silently
skipped):
- Acceptance criterion "OSS index queryable via `opensearchpy`" — needs a
  deployed collection and a live query.
- Acceptance criterion "SNS delivery status logs written to CloudWatch" —
  needs both real subscriptions and live message delivery.
- Whether the `#`-in-attribute-name convention above matches what
  `adapters` phase-05 actually implements when it lands (sprint step 09) —
  if that phase's author reads the spec differently, reconcile there
  rather than silently diverging.
