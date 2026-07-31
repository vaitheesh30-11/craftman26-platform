# ADR 0029 — backend phase-04: Audit & Reports — evidence ref grammar, health-endpoint registries, divergence table gaps

Status: accepted
Date: 2026-07-31

## Context

`backend/docs/phase-04-audit-reports.txt` specifies four things that turned
out to be real spec ambiguities, not implementation details, once actually
built against the rest of the codebase:

1. **`GET /evidence/{ref}`'s `ref` grammar.** §4 step 3 says the input is
   `<bucket>/<key>@<version_id>` with "URL-safe encoding" but doesn't say
   whether that means a wrapper encoding (base64, percent-encoding a single
   opaque token) or a literal path segment. `EvidenceClient.verify()`
   (adapters phase-04) also assumes the caller already holds a populated
   `EvidenceRef` (signature, sha256, kms_key_arn) — it has no path that
   resolves a bare S3 location into one.
2. **`GET /operations/health`'s "every known breaker" / "DLQs".** §4 step 2
   says "read `SentinelBreakers` for every known breaker" and
   "`sqs:GetQueueAttributes` for DLQs", but no table, SSM parameter, or code
   constant anywhere in the repo enumerates "every breaker" or "every DLQ
   queue URL" — `SentinelBreakers` is a bare key-value table (`BreakerAccessor.
   state(name)` needs a name you already know), and DLQ URLs only exist
   inside each stack's own CDK synth output.
3. **`GET /operations/divergence`'s backing table.** `DivergenceRecord`
   (`agents/docs/phase-15-dual-mode-execution.txt §5`) has no `feature_id`
   field, but the spec's own GSI ("`feature_id#divergence_kind`") and
   `aws-infra`'s already-provisioned `SentinelDivergence` table (`_TableSpec`
   in `foundation_stack.py`, GSI `feature-divergence-index` pk=`feature_id`
   sk=`divergence_kind` — two plain attributes, not one composite string)
   both assume it exists on the stored record.
4. No producer for `SentinelDivergence` exists yet (agents phase-15, Wave 8)
   — same "build the reader against the documented contract before the
   producer lands" shape as `FaultsClient` (backend phase-01) and
   `LambdaInvokeClient` (backend phase-01, ADR 0018).

## Decision

1. **Evidence ref is a literal path segment, not a wrapper encoding.**
   `routers/evidence.py` declares `GET /evidence/{ref:path}` and
   `evidence_service.parse_evidence_ref` splits on the *last* `@` (version
   id) then the *first* `/` (bucket vs. key). This is safe for every ref
   this platform itself ever mints: `derive_evidence_key` (adapters
   phase-04) never emits a key containing `@`, and S3 bucket names cannot
   contain `/`. `EvidenceClient` grew `resolve_ref()` (a `head_object` that
   recovers `signature`/`sha256`/`kms_key_arn` from the S3 object metadata
   `put_signed_evidence` already writes) and `verify_by_location()` (resolve
   + delegate to the existing `verify()` — no parallel canonicalize/hash/
   verify logic was written). `resolve_ref` returns `None` for a
   missing object/version (mapped to 404), and lets a genuine signature
   mismatch raise `EvidenceVerificationError` (now mapped in `errors.py` to
   **502**, per §4 step 3's own contract) — the two failure modes the spec
   distinguishes.
2. **Health-endpoint registries are settings-driven, not discovered.**
   `AdapterSettings.known_breaker_names` (defaults to every breaker name
   real code calls today: all `DynamoDbHelper`-backed table names plus
   `bedrock`/`zelkova`) and `AdapterSettings.dlq_queue_urls` (defaults empty
   — no deployed stack has published real queue URLs to this environment
   yet) are both comma-separated env-configurable strings.
   `OperationsService.get_health()` reads both, calls `BreakerAccessor.
   state(name)` per breaker and `DlqClient.get_depth(url)` per queue, and
   composes them. A live AWS-side enumeration (e.g. `cloudformation:
   DescribeStacks` across every stack) was rejected as out of scope for a
   ≤300ms p95 read endpoint and not something any other phase in this repo
   does.
3. **`DivergenceClient` treats `feature_id` as a plain dict key**, same
   module-boundary rule as `FaultsClient`/`ReportsClient` (backend never
   validates against the `agents` Pydantic contract) — the eventual
   producer's job is to write it; this reader's GSI query
   (`list_recent(feature_id=..., divergence_kind=...)`) matches the real,
   already-provisioned two-attribute GSI, not the spec prose's composite-key
   phrasing.
4. **No access-control scoping on `/reports/*` or `/operations/*`** beyond
   requiring an authenticated principal — same precedent
   `services/operations_service.py`'s existing docstring already
   established for `/operations/faults`/`cost/weekly`: these are
   operator-facing observability views, not principal-scoped data. §5's
   "no evidence access for non-Auditor/Operator groups" rule is enforced
   only on `GET /evidence/{ref}` (`evidence_service._is_privileged`, the
   exact same auth-kind/group-membership pattern `findings_service.
   _is_privileged` already uses — duplicated per-service, not factored into
   a shared helper, matching this repo's established convention).

## Consequences

Deferred (tracked here, not silently dropped):

1. §4 step 3's "every retrieval emits a `SentinelEvidenceReads` metric and a
   signed access-log entry" — the metric is cheap and structurally
   straightforward but the *signed* access-log entry implies writing a new
   `EvidenceRecord` for every read (a self-referential audit trail), which
   is a real, separate deliverable this phase did not have budget for. Not
   built; re-open when this endpoint sees real traffic.
2. `dlq_queue_urls` defaults empty — no deployed stack publishes real queue
   URLs to SSM/an env var yet (every DLQ that exists today
   — `SessionKillQueue-DLQ.fifo`, every `SentinelLambda`'s own DLQ, the
   Athena/Bedrock/security-stack DLQs — is only visible inside its owning
   stack's CDK synth output). `GET /operations/health` is code-complete and
   will report real depths the moment an operator sets that env var;
   whoever wires a real deploy pipeline should also export those URLs.
3. `SentinelDivergence` has no producer yet (agents phase-15, Wave 8) — this
   endpoint will show nothing but empty pages until that phase lands and
   starts writing `feature_id`-bearing records.
4. §7's "≤300ms p95" latency acceptance criterion is design-bounded (no new
   full-table scans on the hot path; `GET /operations/health` is a small,
   bounded number of `GetItem`/`GetQueueAttributes` calls), not measured —
   no deployed Lambda/API Gateway target exists yet, same gap every prior
   backend phase has already deferred.
