# Sentinel-IQ v8 — Epics and User Stories

GitHub-Issue-ready delivery matrix. Every story below can be pasted as an Issue verbatim: title, description, acceptance criteria, dependencies, labels, estimate. Estimates: XS <1d, S 1-2d, M 3-5d, L 1-2w, XL 3+w.

---

## Epic 1 — Repository Infrastructure, Contracts, and AI Memory Setup

Foundational scaffolding, contracts, and AI-agent context memory. Prerequisite for every other epic.

### Story 1.1 — Bootstrap monorepo tooling
**Description**: Provision the top-level tool configuration for a mixed Python + TypeScript monorepo without adding any application code.
**Acceptance Criteria**:
- [ ] `pyproject.toml` at repo root pinning Python 3.11+, ruff, mypy, pytest.
- [ ] `package.json` at repo root pinning Node 20+ and pnpm 9+ with workspace declarations for `frontend`, `backend-api-types`, `aws-infra`, `adapters-types`.
- [ ] `.editorconfig`, `.gitignore`, `.gitattributes`, `.nvmrc`, `.python-version`.
- [ ] CI configuration file (`.github/workflows/ci.yml`) that runs lint + type-check on every push.
**Labels**: `epic:1`, `type:infra`, `blocks-all`
**Estimate**: S

### Story 1.2 — Finalize `SYSTEM_STATE.md` universal memory
**Description**: Ensure the root `SYSTEM_STATE.md` is the single AI-agent onboarding document. Must reference every subfolder README and every contract in `docs/`.
**Acceptance Criteria**:
- [ ] Sections match sections 1-6 of the current `SYSTEM_STATE.md`.
- [ ] Directory map is complete and matches on-disk state.
- [ ] Cross-module integration matrix lists every producer/consumer pair with a validated contract.
**Labels**: `epic:1`, `type:docs`
**Estimate**: XS

### Story 1.3 — Publish central contracts
**Description**: `docs/DATA_CONTRACTS.md` and `docs/API_SPEC.md` become the single source of truth for cross-service interfaces.
**Acceptance Criteria**:
- [ ] All four models fully specified: `DiffArtifact`, `SpecialistVerdict`, `DecisionRecord`, `IntentBaseline`.
- [ ] REST spec covers `/drift`, `/drift/{id}`, `/decisions`, `/decisions/{id}/approve`, `/baselines` (GET+POST).
- [ ] WebSocket spec covers handshake, ping/pong, and four event frames.
- [ ] Error envelope documented.
**Labels**: `epic:1`, `type:docs`
**Estimate**: S

### Story 1.4 — Wire pre-commit contract-parity check
**Description**: Prevent contract drift between the docs and any implementation stubs.
**Acceptance Criteria**:
- [ ] Pre-commit hook runs a checksum comparison between `docs/DATA_CONTRACTS.md` and any implementation-generated declarations.
- [ ] CI fails when the docs are changed without a corresponding implementation update flag.
**Labels**: `epic:1`, `type:ci`
**Estimate**: M

---

## Epic 2 — Real-Time Event Ingestion & Normalizer Pipeline (AWS Infra)

Capture every drift-relevant AWS event, canonicalize, dedup, and hand off to the Decision Lambda. All work belongs in `aws-infra/`.

### Story 2.1 — EventBridge management-event rule
**Description**: CDK-deployed rule targets Normalizer Lambda for IAM/Org/IC/STS/resource-policy write actions.
**Acceptance Criteria**:
- [ ] Rule ARN emitted as CDK output.
- [ ] Rule pattern matches the published action list in `aws-infra/README.md` section "Event Sources".
- [ ] Deploys clean via `pnpm cdk deploy events-stack`.
**Labels**: `epic:2`, `type:infra`
**Estimate**: S

### Story 2.2 — SQS main queue and DLQ with alarms
**Description**: Backpressure queue between EventBridge and Normalizer + DLQ + CloudWatch alarms.
**Acceptance Criteria**:
- [ ] SQS main queue with visibility timeout ≥ Normalizer max exec time.
- [ ] DLQ with 14-day retention and `redrive-allow-policy`.
- [ ] Alarm fires on DLQ depth > 0 for 5 minutes.
**Labels**: `epic:2`, `type:infra`
**Estimate**: XS

### Story 2.3 — Normalizer Lambda
**Description**: Consumes CloudTrail events, produces `DiffArtifact` per `docs/DATA_CONTRACTS.md`.
**Acceptance Criteria**:
- [ ] Canonicalization keyed by `(resource_arn, change_hash, actor_arn, 5-minute-window)`.
- [ ] Duplicate events within window are suppressed.
- [ ] Output persisted to S3 evidence bucket and forwarded to Decision SQS.
- [ ] All six drift surfaces handled.
- [ ] `scp_bytes_size` populated for SCP surface.
**Labels**: `epic:2`, `type:lambda`
**Estimate**: L
**Depends on**: 2.1, 2.2, 4.5, 4.6

### Story 2.4 — CloudTrail Lake retrospective backfill Lambda
**Description**: 15-minute schedule; emits missing NormalizedChange events; alarms on non-empty gap.
**Acceptance Criteria**:
- [ ] EventBridge Scheduler cadence 15 min.
- [ ] Compares CloudTrail Lake query output vs. observed evidence keys.
- [ ] Enqueues missing events with `backfill=true` flag.
- [ ] CloudWatch alarm on non-empty gap for 2 consecutive runs.
**Labels**: `epic:2`, `type:lambda`
**Estimate**: M

### Story 2.5 — Config aggregator divergence sanity Lambda
**Description**: Compares Config snapshot to evidence lake, emits divergence alarm only.
**Acceptance Criteria**:
- [ ] 15-minute cadence.
- [ ] Never emits a NormalizedChange (this is a sanity channel, not a decision channel).
- [ ] Alarm on non-empty divergence.
**Labels**: `epic:2`, `type:lambda`
**Estimate**: S

---

## Epic 3 — Deterministic Decision Engine & Zelkova Verification Engine (Backend/Infra)

Implement the rule engine and Zelkova adapter. Work spans `backend/`, `adapters/`, `aws-infra/`.

### Story 3.1 — Rule table in DynamoDB
**Description**: Ordered rule set R0-R8 stored as a versioned JSON artifact in DynamoDB.
**Acceptance Criteria**:
- [ ] Table `SentinelIQ-Rules` with `versionId` PK and `orderIndex` SK.
- [ ] JSON Schema validator on writes rejects invalid rule shapes.
- [ ] Every mutation writes a signed audit record to the evidence bucket.
**Labels**: `epic:3`, `type:infra`
**Estimate**: S

### Story 3.2 — Seed reference ruleset R0-R8
**Description**: Load the reference rules exactly as documented in `docs/ARCHITECTURE.md` section 1.1.
**Acceptance Criteria**:
- [ ] R0 through R8 present with correct predicates and actions.
- [ ] R5 SCP byte-size threshold set to 5,000.
- [ ] R6 requires Zelkova pre-check pass.
**Labels**: `epic:3`, `type:data`
**Estimate**: XS

### Story 3.3 — Decision Lambda skeleton
**Description**: Read `DiffArtifact` from SQS, load current rule set, evaluate R0-R6, either emit `DecisionRecord` or dispatch to Council Step Functions.
**Acceptance Criteria**:
- [ ] Latency p95 < 500 ms end-to-end for deterministic path.
- [ ] Signed `DecisionRecord` emitted on match.
- [ ] Escapes to Council path with input including baseline snippet and context signals.
- [ ] Unit tests cover every rule with property-based fuzz input.
**Labels**: `epic:3`, `type:lambda`
**Estimate**: L
**Depends on**: 3.1, 3.2, 4.5, 4.6

### Story 3.4 — Zelkova client (`CheckNoNewAccess`)
**Description**: Boto3-based adapter with retry, error normalization, and evidence emission.
**Acceptance Criteria**:
- [ ] `check_no_new_access(existing_policy, new_policy) -> ZelkovaResult` returns `pass` or `violation` with witness.
- [ ] Every invocation logged to evidence lake with signed record.
- [ ] Handles throttling with exponential backoff.
**Labels**: `epic:3`, `type:adapter`
**Estimate**: M

### Story 3.5 — Rule R6 gates AutoRemediate on Zelkova pass
**Description**: The only rule that permits AutoRemediate MUST include Zelkova pre-check.
**Acceptance Criteria**:
- [ ] R6 evaluation calls Zelkova client synchronously.
- [ ] Fail-open impossible: adapter error → R6 does not fire → escalate.
- [ ] Integration test with mocked Zelkova pass and fail cases.
**Labels**: `epic:3`, `type:integration`
**Estimate**: M
**Depends on**: 3.3, 3.4

### Story 3.6 — Rule R5 SCP byte-size predicate
**Description**: Deterministic check inside R5 that downgrades AutoRemediate to RequestApproval when candidate SCP > 5,000 bytes.
**Acceptance Criteria**:
- [ ] Candidate SCP body is byte-size-measured before evaluation.
- [ ] Any candidate > 5,000 bytes → action `RequestApproval` with published rationale.
- [ ] Unit tests cover boundary sizes 4999, 5000, 5001, 5120.
**Labels**: `epic:3`, `type:lambda`
**Estimate**: S

---

## Epic 4 — Specialist Agents & Step Functions Express Orchestration (Agents/Infra)

Implement the five reasoning agents (IIA, CSA, BRA, CAA, GC) and the Express Workflow that orchestrates them.

### Story 4.1 — Prompt sanitization utility
**Description**: `<untrusted_context>` XML fencing, Pydantic typing, forbidden-pattern rejection.
**Acceptance Criteria**:
- [ ] Sanitizer rejects control chars, angle brackets, backticks, forbidden phrases (`ignore prior instructions`, `Human:`, `Assistant:`, `</system>`).
- [ ] Wraps sanitized values in `<untrusted_context type="...">` fences.
- [ ] Prompt-injection test suite with 100+ payloads passes.
**Labels**: `epic:4`, `type:adapter`, `security`
**Estimate**: M

### Story 4.2 — Bedrock Guardrail configuration
**Description**: Published single Guardrail applied to every Bedrock invocation.
**Acceptance Criteria**:
- [ ] Guardrail deployed via CDK custom resource.
- [ ] Guardrail ID exported as SSM parameter.
- [ ] Denied topics, PII entities, contextual grounding thresholds match `docs/ARCHITECTURE.md` section 5.
**Labels**: `epic:4`, `type:infra`, `security`
**Estimate**: S

### Story 4.3 — Bedrock runtime client
**Description**: Typed wrapper enforcing sanitization + Guardrail + JSON Schema output validation + forgery check on `cited_evidence_ids`.
**Acceptance Criteria**:
- [ ] Every invocation goes through sanitizer AND Guardrail.
- [ ] JSON Schema output enforced.
- [ ] Forgery check rejects outputs containing strings not present in sanitized input.
- [ ] Model routing: Haiku default; Sonnet by explicit caller opt-in.
**Labels**: `epic:4`, `type:adapter`
**Estimate**: M
**Depends on**: 4.1, 4.2

### Story 4.4 — IIA (Intent Interpretation Agent)
**Description**: Structured verdict on whether drift violates baseline intent.
**Acceptance Criteria**:
- [ ] Emits `SpecialistVerdict[agent_id=IIA]`.
- [ ] Conservative default on failure: `verdict=violated, confidence=0`.
- [ ] p95 latency < 2 s.
- [ ] Unit tests cover aligned, ambiguous, violated cases.
**Labels**: `epic:4`, `type:agent`
**Estimate**: M
**Depends on**: 4.3

### Story 4.5 — CSA (Context Synthesis Agent)
**Description**: Synthesize business signals into a coherence narrative.
**Acceptance Criteria**:
- [ ] Emits `SpecialistVerdict[agent_id=CSA]`.
- [ ] `missing_signals` populated when required signals absent.
- [ ] Conservative default: `coherence_score=0, missing_signals=["all"]`.
- [ ] p95 latency < 3 s.
**Labels**: `epic:4`, `type:agent`
**Estimate**: M
**Depends on**: 4.3

### Story 4.6 — BRA (Blast Radius Analyst)
**Description**: Deterministic reachability + verbatim runbook citation. No synthesis about external systems.
**Acceptance Criteria**:
- [ ] Emits `SpecialistVerdict[agent_id=BRA]`.
- [ ] `runbook_cited_impact` fragments are byte-verified against retrieved runbook content.
- [ ] Conservative default: `overall_severity=critical, rollback_safety=unsafe`.
- [ ] p95 latency < 5 s.
**Labels**: `epic:4`, `type:agent`
**Estimate**: L
**Depends on**: 4.3, 3.4

### Story 4.7 — CAA (Compliance Advisor Agent)
**Description**: Map drift to compliance controls via Bedrock Knowledge Base retrieval.
**Acceptance Criteria**:
- [ ] Emits `SpecialistVerdict[agent_id=CAA]`.
- [ ] `controls_affected` entries reference KB fragments verbatim.
- [ ] Conservative default: `scope_change=unknown`.
- [ ] p95 latency < 5 s.
**Labels**: `epic:4`, `type:agent`
**Estimate**: L
**Depends on**: 4.3

### Story 4.8 — Governance Council Orchestrator
**Description**: Synthesize four specialist verdicts, resolve dissent, emit `DecisionRecord`.
**Acceptance Criteria**:
- [ ] Haiku default; Sonnet escalation when dissent rate > 0.5.
- [ ] Cannot emit `AutoRemediate` if R0 or R5 fired.
- [ ] `dissenting_opinions` populated for every specialist whose recommended action differs from the chosen one.
- [ ] p95 workflow (parallel + Council) < 45 s.
**Labels**: `epic:4`, `type:agent`
**Estimate**: L
**Depends on**: 4.4, 4.5, 4.6, 4.7

### Story 4.9 — Express Workflow ASL with ResultPath aggregation
**Description**: Step Functions Express Workflow definition per `docs/ARCHITECTURE.md` section 6.
**Acceptance Criteria**:
- [ ] Parallel state with four branches (IIA, CSA, BRA, CAA) aggregating to `$.specialists`.
- [ ] No DynamoDB writes between branches.
- [ ] Council invocation input includes `$.specialists`, diff, and baseline snippet.
- [ ] Workflow definition validated via `sfn validate-state-machine-definition`.
**Labels**: `epic:4`, `type:workflow`
**Estimate**: M
**Depends on**: 4.4-4.8

---

## Epic 5 — FastAPI Backend Service & WebSocket Real-time Router (Backend)

All work in `backend/`. Exposes the REST + WebSocket contract defined in `docs/API_SPEC.md`.

### Story 5.1 — FastAPI application shell
**Description**: App factory, CORS, middleware, error handlers, structured logging, Lambda web adapter.
**Acceptance Criteria**:
- [ ] Boots locally with `uvicorn` and under `mangum` for Lambda.
- [ ] OpenAPI spec generated at `/openapi.json`.
- [ ] Error envelope matches `docs/API_SPEC.md` section 8.
**Labels**: `epic:5`, `type:backend`
**Estimate**: S

### Story 5.2 — `GET /api/v1/drift` and `/drift/{id}`
**Description**: Paginated feed + single-drift deep dive.
**Acceptance Criteria**:
- [ ] Cursor-based pagination; opaque cursors are URL-safe.
- [ ] Filters (severity, drift_surface, account_id, since) all functional.
- [ ] Response validates against `DiffArtifact` schema.
**Labels**: `epic:5`, `type:backend`
**Estimate**: M

### Story 5.3 — `GET /api/v1/decisions`
**Description**: Historical DecisionRecord feed with filters.
**Acceptance Criteria**:
- [ ] Filters: action, councilInvoked, dissentGteRate.
- [ ] Response validates against `DecisionRecord` schema.
**Labels**: `epic:5`, `type:backend`
**Estimate**: S

### Story 5.4 — `POST /api/v1/decisions/{id}/approve`
**Description**: Resumes Step Functions Standard Workflow via callback token.
**Acceptance Criteria**:
- [ ] Two-signer corroboration enforced for Tier-0 resources.
- [ ] Callback token verified against DynamoDB approval-registry.
- [ ] Idempotent under retry: repeated call returns the resolution state.
**Labels**: `epic:5`, `type:backend`, `security`
**Estimate**: M

### Story 5.5 — `GET /api/v1/baselines` and `POST /api/v1/baselines`
**Description**: Baseline read + signed baseline upload.
**Acceptance Criteria**:
- [ ] Upload verifies KMS signature.
- [ ] Regression Zelkova check scheduled asynchronously.
- [ ] `POST` returns 202 with pending state.
**Labels**: `epic:5`, `type:backend`, `security`
**Estimate**: M
**Depends on**: 3.4

### Story 5.6 — WebSocket `/ws/drift` gateway
**Description**: Real-time event stream powered by API Gateway WebSocket + Lambda + DynamoDB connection registry.
**Acceptance Criteria**:
- [ ] Handshake authenticates via Cognito JWT.
- [ ] Ping/pong keepalive every 30 s.
- [ ] All four event frames emitted from Step Functions and Normalizer via SNS fan-out.
**Labels**: `epic:5`, `type:backend`, `realtime`
**Estimate**: L

### Story 5.7 — CORS, auth, and rate limiting
**Description**: Per-account rate limiting; Cognito auth; CORS scoped to the Frontend origin.
**Acceptance Criteria**:
- [ ] `429` with `Retry-After` on limit breach.
- [ ] Unauthenticated request → `401` per error envelope.
- [ ] Preflight passes for the Frontend origin.
**Labels**: `epic:5`, `type:backend`
**Estimate**: S

---

## Epic 6 — Enterprise Governance Dashboard (Frontend)

All work in `frontend/`. Next.js 14 App Router.

### Story 6.1 — App Router shell + shared layout
**Description**: Root layout, nav shell, theme, typography, dark-mode-only styling for the SOC audience.
**Acceptance Criteria**:
- [ ] `/`, `/drift`, `/baseline` routes render with the shared layout.
- [ ] TypeScript strict mode passes.
- [ ] Lighthouse a11y score ≥ 95.
**Labels**: `epic:6`, `type:frontend`
**Estimate**: S

### Story 6.2 — `use-drift-socket` custom WebSocket hook
**Description**: Auth handshake, reconnect with backoff, ping/pong.
**Acceptance Criteria**:
- [ ] Reconnects with exponential backoff up to 60 s.
- [ ] Emits typed events matching `docs/API_SPEC.md` section 7.
- [ ] Auth token refresh handled transparently.
**Labels**: `epic:6`, `type:frontend`
**Estimate**: M

### Story 6.3 — `drift-feed-card` component
**Description**: Per-drift card with severity chip, action badge, actor summary, timestamp, and Council-invocation indicator.
**Acceptance Criteria**:
- [ ] Renders `DiffArtifact` + latest `DecisionRecord` inline.
- [ ] Click opens `council-modal`.
- [ ] Skeleton state during network fetch.
**Labels**: `epic:6`, `type:frontend`
**Estimate**: M

### Story 6.4 — `council-modal` reasoning viewer
**Description**: Displays the four `SpecialistVerdict` outputs, Council rationale, dissenting opinions, cited evidence links, and Zelkova pre/post results.
**Acceptance Criteria**:
- [ ] Renders each verdict as a labeled block.
- [ ] Dissenting opinions highlighted.
- [ ] Cited evidence ids link out to the evidence lake viewer.
**Labels**: `epic:6`, `type:frontend`
**Estimate**: M

### Story 6.5 — `approval-modal`
**Description**: Two-signer corroboration UI for `RequestApproval` decisions.
**Acceptance Criteria**:
- [ ] Requires two distinct approver identities for Tier-0 resources.
- [ ] POSTs to `/api/v1/decisions/{id}/approve` with callback token.
- [ ] Displays resulting Step Functions execution ARN.
**Labels**: `epic:6`, `type:frontend`
**Estimate**: M

### Story 6.6 — `zelkova-badge`
**Description**: Visual pass/fail indicator with witness inspection link.
**Acceptance Criteria**:
- [ ] Green when both pre and post checks pass.
- [ ] Amber during 15 s Wait polling.
- [ ] Red on witness violation with clickable witness inspection panel.
**Labels**: `epic:6`, `type:frontend`
**Estimate**: S

### Story 6.7 — `/baseline` viewer
**Description**: Read-only baseline JSON tree, diff since last approved version, upload trigger.
**Acceptance Criteria**:
- [ ] Loads active baseline via `GET /api/v1/baselines`.
- [ ] Renders JSON with syntax highlighting.
- [ ] Upload button opens a modal that calls `POST /api/v1/baselines` with the signed body.
**Labels**: `epic:6`, `type:frontend`
**Estimate**: M

---

## Epic 7 — Security Hardening, Prompt Fencing, and End-to-End Test Suite

All work spans repositories; primary owner is the security team.

### Story 7.1 — Prompt-injection corpus
**Description**: Corpus of ≥ 100 payloads exercising every agent.
**Acceptance Criteria**:
- [ ] Corpus stored under `docs/security/prompt-injection-corpus.md` with categorization.
- [ ] Automated test asserts each payload either triggers Guardrail intervention OR returns the agent's conservative default.
- [ ] Zero false-negative tolerance.
**Labels**: `epic:7`, `security`, `type:test`
**Estimate**: L
**Depends on**: 4.3-4.8

### Story 7.2 — SCP self-containment boundary test
**Description**: End-to-end test that a compromised admin identity cannot modify Sentinel-IQ roles, boundary, or SCP without break-glass.
**Acceptance Criteria**:
- [ ] Test suite deploys a scratch account and attempts each denied action.
- [ ] Every attempt fails with `AccessDenied`.
- [ ] Break-glass identity issuance is CloudTrail-alarmed.
**Labels**: `epic:7`, `security`, `type:test`
**Estimate**: M
**Depends on**: 3.6 (KMS + SCP), aws-infra

### Story 7.3 — Zelkova regression sampling
**Description**: Curated corpus of drift diffs with expert-labeled expected outcomes.
**Acceptance Criteria**:
- [ ] ≥ 50 curated diffs covering all six drift surfaces.
- [ ] Pipeline compares Zelkova + rule engine output vs expected labels.
- [ ] Report published; divergence > 10 percent triggers rule-set review.
**Labels**: `epic:7`, `type:test`
**Estimate**: L

### Story 7.4 — Load benchmark
**Description**: Sustained 100 decisions/second for 10 minutes.
**Acceptance Criteria**:
- [ ] End-to-end p95 within SLO (Council 45 s, deterministic 500 ms).
- [ ] No throttled SQS or Bedrock errors.
- [ ] Cost delta reported.
**Labels**: `epic:7`, `type:test`
**Estimate**: M

### Story 7.5 — Cost benchmark
**Description**: 100K synthetic drifts; report actual line items vs `docs/ARCHITECTURE.md` section 10.
**Acceptance Criteria**:
- [ ] Report under `docs/cost-benchmarks.md`.
- [ ] Variance under 15 percent from architecture forecast.
**Labels**: `epic:7`, `type:test`
**Estimate**: M

### Story 7.6 — Chaos: rollback failure drill
**Description**: Force Zelkova post-verification to fail on all 3 iterations; verify automatic rollback executes.
**Acceptance Criteria**:
- [ ] Failure injection via feature-flagged Zelkova mock.
- [ ] Rollback plan executes; state converges to baseline.
- [ ] On-call PagerDuty received with full evidence bundle.
**Labels**: `epic:7`, `type:test`, `chaos`
**Estimate**: M

### Story 7.7 — Red-team engagement
**Description**: External red team attempts prompt injection through tags, resource names, runbook uploads.
**Acceptance Criteria**:
- [ ] Engagement scope document at `docs/security/red-team-scope.md`.
- [ ] Findings triaged and either fixed or accepted with rationale.
- [ ] Post-engagement report at `docs/security/red-team-findings-<date>.md`.
**Labels**: `epic:7`, `security`
**Estimate**: L
**Depends on**: 7.1

### Story 7.8 — End-to-end scenario tests
**Description**: The three canonical scenarios from the demo narrative pass automated tests in CI.
**Acceptance Criteria**:
- [ ] Legitimate deploy scenario passes.
- [ ] Ambiguous break-glass without signed ticket scenario passes.
- [ ] Silent SCP detach with autonomous remediation scenario passes.
**Labels**: `epic:7`, `type:test`, `demo`
**Estimate**: L

---

## Summary

Total stories: 43 across 7 epics. Convert each Story block above directly into a GitHub Issue: use `### Story X.Y — Title` as the Issue title, everything below (Description, Acceptance Criteria checklist, Labels, Estimate, Depends on) as the Issue body.

Track live status by editing this file and referencing Issue links in the `**Labels**` line, or by mirroring into a GitHub Project.
