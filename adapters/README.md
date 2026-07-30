# adapters/ — AWS API Adapters and Cryptographic Utilities

The single, audited surface through which every IAM Sentinel Lambda talks to AWS. Adapters encapsulate boto3 clients, retry policy, error normalization, evidence emission, XML prompt fencing, Zelkova pre/post-check semantics, KMS signing, and cost metering.

Authoritative canon: `SYSTEM_STATE.md`, `docs/ARCHITECTURE.md`, `docs/AGENTIC_DESIGN.md`, `docs/DATA_CONTRACTS.md`.

---

## 1. Module Purpose and System Boundaries

**Purpose.** Provide typed, resilient, cost-metered, evidence-emitting adapters for every AWS API Sentinel touches. No Lambda in the platform makes a raw boto3 call — every AWS interaction happens through an adapter.

**In scope.**
- Bedrock runtime + Bedrock agent-runtime adapters (Converse, InvokeAgent, InvokeAgentWithResponseStream, Retrieve).
- Access Analyzer Zelkova adapter (`CheckNoNewAccess`, `CheckAccessNotGranted`, `StartPolicyGeneration`, `GetGeneratedPolicy`, `ListFindings`, `UpdateFindings`, `CreateArchiveRule`).
- Prompt fencer + sanitizer.
- Security Hub ASFF adapter.
- KMS-signed S3 Object Lock evidence adapter.
- DDB single-table helpers (findings, decisions, memory, budget, breakers).
- Cost meter primitives.
- Retry primitives and circuit-breaker state accessors.

**Out of scope.**
- Business logic (owned by `agents/`).
- REST/WebSocket handling (owned by `backend/`).
- CDK infrastructure (owned by `aws-infra/`).

**Boundaries.**
- Imported by: `agents/`, `backend/`, and Lambdas defined under `aws-infra/functions/`.
- Never imports from `agents/`, `backend/`, or `frontend/`.
- Depends on `docs/DATA_CONTRACTS.md` for typed payloads.

---

## 2. Directory Tree

```
adapters/
├── README.md                       this file
├── pyproject.toml                  uv-managed, Python 3.12
├── docs/
│   ├── README.md                   phase index
│   ├── phase-00-adapters-foundations.txt
│   ├── phase-01-bedrock-adapter.txt
│   ├── phase-02-zelkova-adapter.txt
│   ├── phase-03-prompts-adapter.txt
│   ├── phase-04-evidence-adapter.txt
│   └── phase-05-ddb-adapter.txt
├── src/
│   └── iam_sentinel_adapters/
│       ├── __init__.py
│       ├── settings.py             pydantic-settings config
│       ├── errors.py               exception hierarchy
│       ├── retry.py                @retry decorator + policies
│       ├── circuit_breaker.py      state accessor for phase-16
│       ├── cost_meter.py           spend accounting (phase-16)
│       ├── bedrock/
│       │   ├── __init__.py
│       │   ├── client.py           Converse + InvokeAgent wrappers
│       │   ├── model_router.py     Haiku default, Sonnet on demand
│       │   ├── guardrail.py        Guardrail ID accessor
│       │   └── output_validator.py Forged-string check
│       ├── zelkova/
│       │   ├── __init__.py
│       │   ├── client.py           CheckNoNewAccess + friends
│       │   └── models.py           ZelkovaResult, Witness
│       ├── prompts/
│       │   ├── __init__.py
│       │   ├── xml_fencer.py       <trusted_input> / <untrusted_context>
│       │   └── sanitizer.py        NFKC + forbidden-pattern rejector
│       ├── evidence/
│       │   ├── __init__.py
│       │   ├── client.py           KMS-signed PutObject
│       │   ├── canonicalize.py     RFC 8785 JCS
│       │   ├── keys.py             content-addressed key derivation
│       │   ├── kms_signer.py       kms:Sign with DIGEST
│       │   └── kms_verifier.py     kms:Verify + pubkey cache
│       ├── security_hub/
│       │   ├── __init__.py
│       │   ├── client.py           BatchImportFindings
│       │   └── asff_mapper.py      Finding → ASFF
│       ├── ddb/
│       │   ├── __init__.py
│       │   ├── findings.py
│       │   ├── decisions.py
│       │   ├── memory.py           episodic + semantic + procedural
│       │   ├── budget.py           SpendSample + BudgetSnapshot
│       │   ├── breakers.py
│       │   └── in_flight.py        SentinelDecisionsInFlight
│       └── memory/
│           └── client.py           High-level recall/remember wrapper
└── tests/
    ├── unit/
    ├── prompt_injection/
    └── property/
```

---

## 3. Tech Stack

- Python 3.12.
- `boto3==1.35.36` (via Lambda layer at runtime; pinned at build).
- `pydantic==2.9.2`, `pydantic-settings==2.5.2`.
- `tenacity==8.5.0` (retry primitives).
- `aws-lambda-powertools[all]==2.42.0` (logger + metrics used inside adapters for observability).
- `hypothesis==6.112` (property tests on sanitizer + retry).
- `moto[all]==5.0.16` (AWS mocks in tests).
- Forbidden: LangChain, LlamaIndex, LiteLLM, LangGraph, any generic "AI SDK" wrapping Bedrock.

---

## 4. Roadmap

| Phase | File                                          | Owner assumption          |
|-------|-----------------------------------------------|---------------------------|
| 00    | `phase-00-adapters-foundations.txt`           | 1 principal engineer      |
| 01    | `phase-01-bedrock-adapter.txt`                | 1 principal engineer      |
| 02    | `phase-02-zelkova-adapter.txt`                | 1 principal engineer      |
| 03    | `phase-03-prompts-adapter.txt`                | 1 principal engineer      |
| 04    | `phase-04-evidence-adapter.txt`               | 1 principal engineer      |
| 05    | `phase-05-ddb-adapter.txt`                    | 1 principal engineer      |

Six phases; the roadmap can be executed by six engineers in parallel after phase-00 lands.

---

## 5. Contract with Callers

- Every adapter method takes typed inputs (Pydantic v2) and returns typed outputs.
- Every failure raises a domain exception from `errors.py`. Callers translate to their own conservative-default failure mode.
- Every method emits telemetry: Powertools log line, X-Ray subsegment, and (for Bedrock/Athena/Zelkova) cost meter samples.
- Retries happen inside adapters; callers see only the final outcome or a domain exception.
- No adapter is aware of higher-level types (`SpecialistVerdict`, `DecisionRecord`) except at the Security Hub ASFF mapping layer, which consumes `Finding`.

---

## 6. Acceptance Criteria (Module-Wide)

- `uv run ruff check adapters/` clean.
- `uv run mypy --strict adapters/src` clean.
- `pytest adapters/tests` ≥ 92% line coverage.
- Property tests (sanitizer, retry, canonicalization) run ≥ 1,000 examples each with zero counterexamples.
- Prompt-injection smoke suite (20 payloads at adapter layer) covered.
- `moto` covers every boto3 call; live smoke tests only in an opt-in integration suite.
