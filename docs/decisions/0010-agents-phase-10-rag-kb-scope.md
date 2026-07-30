# ADR 0010 — agents phase-10: RAG knowledge base scope, cross-module split, deferred criteria

Status: accepted
Date: 2026-07-30

## Context

`agents/docs/phase-10-rag-knowledge-base.txt` §2 lists deliverables that are
almost entirely `aws-infra` and standalone-service concerns: two S3 buckets,
a Bedrock `CfnKnowledgeBase`, a new OpenSearch Serverless collection
(`sentinel-kb`, distinct from adapters phase-05/aws-infra phase-02's
`sentinel` memory collection), a weekly web-scraping Lambda hitting
`docs.aws.amazon.com`, a nightly ingestion-trigger Lambda, and a CDK stack
(`SentinelKBStack`). None of this has a corresponding `aws-infra` sprint
step anywhere in `docs/EXECUTION_STATE.txt` §SPRINT PROGRESS — sprint step
13 is `agents phase-10` alone, on `feat/agents-rag`, with no paired
infra branch the way (for example) `agents phase-04`/`aws-infra phase-03`
are paired.

Two things already existed on `main` before this phase started, which
narrows what's actually left to build:

1. `Finding.aws_doc_citation.quote`'s manifest-checking validator
   (`agents/contracts/finding.py`) already existed, built during
   `agents phase-00`, with a pluggable `QuoteManifest` Protocol and a test
   fixture provider (`agents/tests/conftest.py`). `AgentSettings` already
   had placeholder `kb_manifest_path`/`kb_manifest_refresh_seconds` fields
   anticipating this phase.
2. `adapters phase-01`'s `BedrockProvider.retrieve()` already wraps
   `bedrock-agent-runtime:Retrieve` end-to-end (§4 step 3's actual runtime
   query path), returning `KnowledgeChunk`. `GrokProvider.retrieve()`
   already degrades to an empty list for local dev (no vector store to
   substitute).

What was missing, and is real `agents`-module work independent of a
deployed KB: the `QuoteHash`/`KbManifest` contracts (§3), the pure-Python
manifest generation logic (§4 step 1-2: sentence tokenization, span
windowing, hashing), the KMS-sign/verify S3 boundary for the manifest, a
production `QuoteManifest` provider that replaces the test fixture, and the
freshness contract (§4 step 6) on top of the retrieval path that already
existed.

## Decision

Scope this phase to what `agents/` and a minimal `adapters/` extension can
own directly, without a deployed AWS account or a CDK stack that doesn't
exist yet:

- **Contracts**: `QuoteHash`/`KbManifest` added to
  `agents/contracts/knowledge_base.py`, matching §3 exactly, plus two
  internal-consistency validators the spec implies but doesn't spell out
  (`span_end > span_start`, `total_quotes == len(quotes)`).
- **Manifest generation** (§4 steps 1-2): `agents/knowledge_base/manifest_builder.py`
  implements the regex sentence tokenizer as the *only* tokenizer, not a
  fallback — no nltk dependency is vendored anywhere in this repo, so the
  spec's "fallback to a regex tokenizer if nltk not vendored" clause
  resolves to always-regex. Span offsets are computed as true UTF-8 byte
  offsets (converting from Python's native character indices), matching
  the interface contract's `span_start`/`span_end: byte offset`.
- **Manifest sign/verify boundary**: `adapters/knowledge_base/manifest_client.py`
  (`KbManifestClient`) mirrors `evidence/client.py`'s canonicalize ->
  sha256 -> kms:Sign|Verify pattern. `agents/knowledge_base/manifest_service.py`
  orchestrates building + signing + publishing (the `kb_manifest_generate`
  Lambda's actual body — deferred is only the CDK/EventBridge wrapper that
  would invoke it on a schedule, not the logic itself).
- **Production manifest provider**: `agents/knowledge_base/manifest_provider.py`
  (`KbManifestProvider`) replaces the test-only fixture at Lambda cold
  start, caching the KMS-verified manifest for
  `settings.kb_manifest_refresh_seconds`.
- **Freshness contract** (§4 step 6): `agents/knowledge_base/freshness.py`
  + `retrieval.py` wrap the *already-existing* `LLMProvider.retrieve()`
  with the 30-day staleness check and `SentinelKbStaleRetrieval` metric.
  No specialist calls `retrieval.py` yet (Prime and F1 land Wave 3) — it's
  exercised by unit tests only, ready for the first adopter.
- **Real cross-module gap found and fixed**: `KnowledgeChunk`
  (`adapters/llm/types.py`) had no `retrieved_on` field, so the freshness
  contract this phase requires had nothing to check. Added
  `retrieved_on: str | None = None`, populated in
  `BedrockProvider.retrieve()` from the Retrieve API's per-result
  `metadata` dict. `None` (Grok's empty-list path, or a KB data source
  without the attribute) is never flagged stale — there's no date to
  compare against.
- **Cross-module wiring**: `agents/pyproject.toml` gained its first-ever
  dependency on `iam-sentinel-adapters` (a `path`/`editable` `[tool.uv.sources]`
  entry, not a published package — this is a monorepo). No prior agents
  phase needed to import adapters directly; this is the first one that
  does (KMS verify + S3 read for the manifest, and the `LLMProvider`
  Protocol for retrieval).

## Consequences

Deferred — tracked in `docs/EXECUTION_STATE.txt`, not silently skipped —
because they need a real AWS dev account, a deployed Bedrock Knowledge
Base, and/or a CDK stack this sprint step doesn't include:

1. `SentinelKBStack` itself: the two S3 buckets, the `sentinel-kb` OSS
   collection, the `aws_bedrock.CfnKnowledgeBase` resource, and
   `SentinelKBRole`. No `aws-infra` sprint step currently pairs with this
   one — flagging here (as ADR 0009 flagged the `sentinel`/`sentinel-f3`
   workgroup mismatch) for whoever schedules the infra work.
2. `kb_corpus_fetch` (weekly AWS-doc scraper) and `kb_ingest_trigger`
   (nightly `StartIngestionJob`) as deployed Lambdas + EventBridge rules.
   The scraper in particular needs real network egress and HTML-structure
   assumptions this environment can't validate.
3. All four §8 acceptance criteria: manifest KMS signature verification is
   code-complete and unit-tested against a hand-written KMS fake (moto has
   no real RSASSA-PSS, matching the `evidence/client.py` precedent), but
   "every canonical AWS quote in `docs/AWS_GAPS.md` passes" needs a real
   generated manifest over the real corpus; nightly ingestion success and
   the 10-golden-probe-query Retrieve check both need a deployed KB.
4. Canary probes (§9 risk mitigation) for scraper HTML-structure drift —
   no scraper is deployed to canary.
5. Testing scope reduced per the revised policy: hand-written KMS fakes
   instead of a Hypothesis whitespace-mutation property run (the existing
   `Finding` citation tests already cover NFKC/whitespace stability from
   `agents phase-00`; this phase doesn't re-derive that).
