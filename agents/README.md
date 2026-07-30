# agents/ — Bedrock Agents and Tool Lambdas

The agentic core of IAM Sentinel. This module owns every Bedrock Agent (Sentinel Prime + 8 specialists), every action-group Lambda (the tools each specialist can call), the prompt templates, the memory configuration, and the eval harness.

Authoritative canon: `SYSTEM_STATE.md`, `docs/ARCHITECTURE.md`, `docs/AGENTIC_DESIGN.md`, `docs/AWS_GAPS.md`, `docs/DATA_CONTRACTS.md`. Read those first.

---

## 1. Module Purpose and System Boundaries

**Purpose.** Convert human natural-language questions and machine event triggers into structured, safe, cited actions against AWS Organizations, IAM, Access Analyzer, Identity Center, and CloudTrail.

**In scope.**
- Bedrock Agent CDK constructs and prompt files (`sentinel_prime` supervisor and `specialists/f1..f8`).
- OpenAPI action-group schemas (one per specialist).
- Lambda tool handlers using `aws_lambda_powertools` (Logger, Tracer, Metrics).
- Prompt templates (`prompts/`) with `<trusted_input>` and `<untrusted_context>` fenced regions.
- Eval harness (`evals/`) — golden inputs, LLM-as-judge scoring, comparison notebooks.

**Out of scope.**
- CDK stacks for storage, networking, IAM roles at the platform level (owned by `aws-infra/`).
- AWS API adapters shared with backend/executor Lambdas (owned by `adapters/`).
- Frontend (owned by `frontend/`).
- Backend REST API (owned by `backend/`).

**Boundaries.**
- Imports from `adapters/` for every AWS call. Never uses raw `boto3` inline in a Lambda handler.
- Imports from `docs/DATA_CONTRACTS.md` schema module for every contract.
- Never imports from `backend/`, `frontend/`, or `aws-infra/`.

---

## 2. Directory Tree (Target)

```
agents/
├── README.md                          this file
├── pyproject.toml                     hatch/uv project; ruff, mypy strict, pytest.
├── docs/                              phase-scoped delivery specs
│   ├── README.md                      roadmap + phase index
│   ├── phase-00-foundations.txt       repo layout, packaging, contracts, tooling
│   ├── phase-01-supervisor-agent.txt  Sentinel Prime
│   ├── phase-02-passrole-cartographer.txt   F1
│   ├── phase-03-org-context-validator.txt   F2
│   ├── phase-04-data-event-enricher.txt     F3
│   ├── phase-05-scp-impact-analyst.txt      F4
│   ├── phase-06-session-terminator.txt      F5
│   ├── phase-07-shadow-guard.txt            F6
│   ├── phase-08-collision-resolver.txt      F7
│   ├── phase-09-slr-guardian.txt            F8
│   ├── phase-10-rag-knowledge-base.txt      Bedrock KB, corpus ingest
│   ├── phase-11-guardrails-safety.txt       Bedrock Guardrails, XML fence, Zelkova
│   ├── phase-12-observability-evals.txt     Powertools, X-Ray, eval harness
│   └── phase-13-integration-tests.txt       moto + contract tests + end-to-end
├── src/
│   └── iam_sentinel_agents/
│       ├── __init__.py
│       ├── contracts/                 Pydantic v2 (mirrors docs/DATA_CONTRACTS.md)
│       │   ├── __init__.py
│       │   ├── common.py              Base, FeatureID, Severity, Verdict
│       │   ├── query.py               SentinelQuery
│       │   ├── task.py                SpecialistTask, UntrustedContextBlock
│       │   ├── verdict.py             SpecialistVerdict, ToolInvocation
│       │   ├── finding.py             Finding, AwsDocCitation
│       │   ├── remediation.py         RemediationPlan, ZelkovaCheck
│       │   ├── evidence.py            EvidenceRecord, EvidenceRef
│       │   └── decision.py            DecisionRecord
│       ├── prompts/
│       │   ├── __init__.py
│       │   ├── prime_supervisor.txt   Sentinel Prime system prompt
│       │   └── specialists/
│       │       ├── f1_passrole.txt
│       │       ├── f2_org_context.txt
│       │       ├── f3_data_event.txt
│       │       ├── f4_scp_impact.txt
│       │       ├── f5_session_kill.txt
│       │       ├── f6_shadow_guard.txt
│       │       ├── f7_collision.txt
│       │       └── f8_slr_guardian.txt
│       ├── action_groups/             OpenAPI 3 schemas per specialist
│       │   ├── f1_passrole.yaml
│       │   ├── f2_org_context.yaml
│       │   ├── f3_data_event.yaml
│       │   ├── f4_scp_impact.yaml
│       │   ├── f5_session_kill.yaml
│       │   ├── f6_shadow_guard.yaml
│       │   ├── f7_collision.yaml
│       │   └── f8_slr_guardian.yaml
│       ├── tools/                     Lambda handlers, one package per feature
│       │   ├── __init__.py
│       │   ├── common/                shared runtime (powertools, XML fencer, sanitizer)
│       │   │   ├── __init__.py
│       │   │   ├── runtime.py
│       │   │   ├── cross_account.py   STS AssumeRole helper
│       │   │   └── event_parser.py    Bedrock action-group envelope
│       │   ├── passrole/              F1 (see phase-02)
│       │   ├── org_context/           F2
│       │   ├── data_event/            F3
│       │   ├── scp_impact/            F4
│       │   ├── session_kill/          F5
│       │   ├── shadow_guard/          F6
│       │   ├── collision/             F7
│       │   └── slr_guardian/          F8
│       └── evals/
│           ├── runner.py              nightly eval driver
│           └── judges.py              LLM-as-judge prompts
├── evals/
│   ├── f1/golden.jsonl
│   ├── f2/golden.jsonl
│   ├── ...
│   └── prime/golden.jsonl
└── tests/
    ├── unit/                          per-tool unit tests (moto)
    ├── contract/                      Pydantic round-trip on every schema
    ├── prompt_injection/              200+ payload smoke corpus
    └── e2e/                           Bedrock Agent dev-alias runs
```

---

## 3. Tech Stack

- Python 3.12 (arm64 Lambda).
- `aws_lambda_powertools[all]` for Logger/Tracer/Metrics/Idempotency/Parser.
- Pydantic v2 for every contract and every tool input/output.
- `boto3` via `adapters/` only. No inline boto3 in handlers.
- `networkx` for F1 blast-radius graphs.
- `pandas` + `pyarrow` for Athena result processing in F3/F4.
- `pytest`, `moto[all]`, `hypothesis`, `pytest-asyncio` for tests.
- `ruff` (lint + format), `mypy --strict` for static checks.
- Forbidden: LangGraph, LangChain, LlamaIndex, LiteLLM, OpenAI SDK, any generic "agent framework" wrapping Bedrock.

---

## 4. Roadmap

Delivery phases are the source of truth. Follow `docs/README.md` for the order and dependencies. Every phase file has an Objective, an Interface Contract, Implementation Steps, Tool Schemas (where applicable), Prompt Templates, IAM Policy, Test Plan, and Acceptance Criteria.

Phase groups:

| Group          | Phases            | Owner assumption           |
|----------------|-------------------|----------------------------|
| Foundations    | phase-00          | Two principal engineers    |
| Supervisor     | phase-01          | One principal engineer     |
| Specialists    | phase-02..09      | 8 parallel engineer streams|
| Cross-cutting  | phase-10..12      | One principal engineer each|
| QA             | phase-13          | Two principal engineers    |

Every phase corresponds to a `feat/agents-*` branch. See `docs/README.md#branches`.

---

## 5. Inputs, Outputs, Integration

**Inputs.**
- `SentinelQuery` from `backend/` (via API Gateway REST or WebSocket).
- EventBridge event patterns for F5 (GuardDuty + IdC assignment) and F6 (mgmt-account CT delivery).
- Scheduled expressions for weekly reports (F6) and SLR DB refresh (F8).

**Outputs.**
- `DecisionRecord` written to `SentinelDecisions` DDB by Prime's post-turn Lambda.
- `Finding` writes to `SentinelFindings` DDB by each specialist tool.
- `EvidenceRecord` KMS-signed and PutObject to `SentinelEvidence` bucket.
- ASFF findings to Security Hub for every critical outcome.
- SNS publishes to `SentinelCriticalFindings` / `SentinelEmergencyRevocations` topics.

**Integration.**
- `adapters/bedrock` — every LLM call (Prime and specialists) is invoked through this adapter with Guardrail ID, model routing, and output-forgery validation.
- `adapters/zelkova` — every policy write goes through pre-check + post-check.
- `adapters/s3_evidence` and `adapters/kms_signer` — every evidence write.
- `adapters/security_hub` — every ASFF submission.
- `aws-infra/` — CDK stacks provision the Agent + KB + Guardrail + Lambdas; agents module owns the source code and the CDK constructs that reference it.

---

## 6. Acceptance Criteria (Module-Wide)

- `ruff check agents/` clean.
- `mypy --strict agents/src` clean.
- `pytest agents/tests/unit agents/tests/contract` ≥ 90% line coverage.
- Prompt-injection corpus: every payload either sanitizer-rejected at ingest OR Guardrail-intervened at output. Zero false negatives.
- Eval harness golden set: verdict accuracy ≥ 95%, citation validity 100% (invalid citations are structurally impossible after the KB-manifest validator).
- End-to-end Bedrock dev-alias run: `POST /agent/chat` with 15 curated prompts returns a valid `DecisionRecord` in < 25 s p95.
