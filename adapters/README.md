# adapters/ — AWS API Wrappers and Cryptographic Utilities

Typed adapters that Every Sentinel-IQ Lambda uses when talking to AWS. Isolating adapters here means the Decision Lambda, Executor Lambda, Backend API, and the five agents all reach AWS through the same audited surface.

---

## 1. Module Purpose and System Boundaries

**Purpose**. Single implementation of every AWS API interaction with retries, error normalization, evidence emission, and testable seams.

**In scope**:
- Access Analyzer Zelkova (`CheckNoNewAccess`) client.
- Bedrock Runtime client with Guardrail + JSON Schema enforcement + Haiku/Sonnet routing.
- XML prompt fencer utility used by every agent.
- Security Hub `BatchImportFindings` client.
- S3 Object Lock evidence storage client (KMS-signed writes).
- KMS asymmetric signer/verifier.
- DynamoDB helpers (rule set reader, in-flight state reader/writer, connection registry helpers).

**Out of scope**:
- Business logic (agents, Council, Executor orchestration).
- Any UI or REST handling.

**Boundaries**:
- Imported by: `agents/`, `backend/`, and Lambdas under `aws-infra/functions/`.
- Never imports from `agents/`, `backend/`, or `frontend/`.
- Depends on `docs/DATA_CONTRACTS.md` for typed payloads.

---

## 2. Files and Directory Tree to Generate

```
adapters/
├── pyproject.toml
├── README.md                          (this file)
├── src/
│   └── sentinel_iq_adapters/
│       ├── __init__.py
│       ├── settings.py                Environment-driven configuration (Pydantic Settings)
│       ├── errors.py                  Domain-specific exception hierarchy
│       ├── retry.py                   Exponential backoff + jitter helpers
│       ├── zelkova/
│       │   ├── __init__.py
│       │   ├── client.py              CheckNoNewAccess wrapper
│       │   └── models.py              ZelkovaResult, Witness types
│       ├── bedrock/
│       │   ├── __init__.py
│       │   ├── client.py              Converse API wrapper with Guardrail + schema
│       │   ├── model_router.py        Haiku default, Sonnet on dissent-rate
│       │   ├── guardrail.py           Guardrail config ID accessor
│       │   └── output_validator.py    Post-response validator (forged-string check)
│       ├── prompts/
│       │   ├── __init__.py
│       │   ├── xml_fencer.py          <trusted_input> and <untrusted_context> composition
│       │   └── sanitizer.py           Character stripping, length capping, forbidden patterns
│       ├── security_hub/
│       │   ├── __init__.py
│       │   ├── client.py              BatchImportFindings wrapper
│       │   └── asff_mapper.py         DecisionRecord → ASFF Finding
│       ├── s3_evidence/
│       │   ├── __init__.py
│       │   ├── client.py              Signed PutObject to Object Lock buckets
│       │   ├── canonicalize.py        Deterministic JSON canonicalization
│       │   └── keys.py                Content-addressed key derivation
│       ├── kms_signer/
│       │   ├── __init__.py
│       │   ├── signer.py              KMS Sign with DIGEST message type
│       │   └── verifier.py            KMS Verify + public-key caching
│       └── dynamodb/
│           ├── __init__.py
│           ├── rules_reader.py
│           ├── in_flight_state.py
│           └── connections.py
└── tests/
    ├── unit/
    │   ├── test_zelkova_client.py
    │   ├── test_bedrock_client.py
    │   ├── test_xml_fencer.py
    │   ├── test_sanitizer.py
    │   ├── test_output_validator.py
    │   ├── test_security_hub_client.py
    │   ├── test_s3_evidence_client.py
    │   ├── test_kms_signer.py
    │   └── test_dynamodb_helpers.py
    └── prompt_injection/
        └── test_corpus.py             Loads 100+ payloads from docs/security/
```

---

## 3. Tech Stack and Recommended Libraries

- Python 3.11+.
- `boto3` (latest).
- Pydantic v2 for typed models and settings.
- `tenacity` for retry with jitter.
- `pytest` + `moto` for AWS mocks.
- `hypothesis` for property-based tests on the sanitizer.
- No LangChain, no llama-index, no LiteLLM. Direct Bedrock is authoritative.

---

## 4. Step-by-Step Implementation Instructions

### 4.1 Zelkova client
1. `client.py` exposes:
   ```
   check_no_new_access(existing_policy: dict, new_policy: dict, *, evidence_id: str) -> ZelkovaResult
   ```
2. Returns `ZelkovaResult(pass_: bool, witness: Optional[Witness], raw_response: dict)`.
3. Every invocation writes a signed evidence record to the Object Lock bucket via `s3_evidence/client.py`.
4. Retries on throttling (max 3 attempts, exp backoff 200ms/500ms/2s).
5. Never fails-open. On unrecoverable error, raises `ZelkovaError` and the caller MUST downgrade to `Escalate`.

### 4.2 Bedrock client
1. `client.py` exposes `invoke_agent(params: BedrockInvocationInput) -> BaseModel` returning a validated Pydantic model.
2. Pipeline:
   1. Compose user prompt via `prompts/xml_fencer.py` from `trusted_input_json` (structured JSON) and a list of `UntrustedContextBlock`.
   2. Call `bedrock-runtime:Converse` with the configured Guardrail.
   3. On `stopReason == "guardrail_intervened"`: raise `GuardrailInterventionError`.
   4. Parse response as JSON, validate against Pydantic model.
   5. Run `output_validator.assert_no_forged_strings(parsed, sanitized_input_set)`.
3. `model_router.pick(dissent_rate: float) -> str` returns Sonnet only when `dissent_rate > 0.5`.

### 4.3 XML fencer + sanitizer
1. `sanitizer.py` implements:
   - Unicode normalization NFKC.
   - Strip Unicode categories starting with `C` (control).
   - Remove `<`, `>`, backticks.
   - Length cap 512.
   - Reject forbidden patterns: `</system`, `</trusted_input`, `</untrusted_context`, `human\s*:`, `assistant\s*:`, `ignore\s+(the\s+)?(previous|above|prior)\s+instructions`.
2. `xml_fencer.build_user_prompt(trusted_input_json, untrusted_blocks) -> str` composes the final prompt with `<trusted_input>` and `<untrusted_context type="...">` fences.

### 4.4 Security Hub client
1. `client.py` exposes `import_findings(findings: list[AsffFinding]) -> BatchImportResult`.
2. `asff_mapper.py` maps a `DecisionRecord` to an ASFF Finding with `ProductArn` set to a Sentinel-IQ product ARN, `Types` including `Software and Configuration Checks/Governance/PolicyDrift`.

### 4.5 S3 evidence client
1. `client.py` exposes `put_signed_evidence(kind: EvidenceKind, body: dict) -> EvidenceRef`.
2. Canonicalizes body via `canonicalize.py`, signs via `kms_signer/signer.py`, writes to Object Lock bucket with content-addressed key from `keys.py`.
3. Verifies signature on every read via `kms_signer/verifier.py`.

### 4.6 KMS signer
1. `signer.py` uses `kms:Sign` with `MessageType=DIGEST`, `SigningAlgorithm=RSASSA_PSS_SHA_256`.
2. `verifier.py` uses `kms:Verify` and caches public keys in-memory with 1-hour TTL.

### 4.7 DynamoDB helpers
1. `rules_reader.py`: load latest rule set version at Lambda cold start; refresh on version-change signal.
2. `in_flight_state.py`: TTL-driven table for R7 workflow tracking.
3. `connections.py`: WebSocket connection registry read/write helpers.

---

## 5. Exact Codex Prompts

**Prompt A — Zelkova client**
> Generate `adapters/src/sentinel_iq_adapters/zelkova/client.py` and `models.py`. Wrap `access-analyzer:CheckNoNewAccess`. Never fail open. On throttling, retry with exponential backoff (200ms, 500ms, 2s). Every invocation emits a signed evidence record. Include `pytest` unit tests with `moto` covering pass, violation with witness, and throttling exhaustion.

**Prompt B — Bedrock client + Guardrail + model routing**
> Generate `adapters/src/sentinel_iq_adapters/bedrock/*` per `adapters/README.md` section 4.2. Guardrail ID is read from `SENTINEL_IQ_GUARDRAIL_ID`. Model router returns Sonnet only when `dissent_rate > 0.5`. Output validator MUST reject any output containing a `cited_evidence_ids` entry not present in the sanitized input set. Include unit tests with a Bedrock stub.

**Prompt C — XML fencer + sanitizer**
> Generate `adapters/src/sentinel_iq_adapters/prompts/*` per section 4.3. Include Hypothesis-based property tests asserting that no combination of sanitized inputs can produce output containing the forbidden patterns. Load 20 payloads from `docs/security/prompt-injection-corpus.md` as a smoke suite (fixtures live in `tests/prompt_injection/fixtures/`).

**Prompt D — Security Hub + ASFF**
> Generate `adapters/src/sentinel_iq_adapters/security_hub/*`. Map `DecisionRecord` to ASFF (Types: `Software and Configuration Checks/Governance/PolicyDrift`; Severity mapped from BRA's `overall_severity`; Resources reference the DiffArtifact's `resource_arn`). Unit tests using `moto`.

**Prompt E — Evidence storage + KMS signer**
> Generate `adapters/src/sentinel_iq_adapters/s3_evidence/*` and `kms_signer/*`. Canonicalize JSON deterministically (sorted keys, no whitespace, UTF-8), sign, write with content-addressed keys. Verify signatures on every read. Include tests using `moto` for both S3 and KMS.

**Prompt F — DynamoDB helpers**
> Generate `adapters/src/sentinel_iq_adapters/dynamodb/*`. Rules reader loads at cold start, refreshes on version-change. In-flight state uses TTL-driven expiration at 24 h. Connection registry supports concurrent read/write from the WebSocket fan-out Lambda.

---

## 6. Inputs, Outputs, and Integration Boundaries

**Inputs**:
- AWS SDK responses (Zelkova, Bedrock, S3, KMS, DynamoDB, Security Hub).
- Sanitized structured payloads from callers.

**Outputs**:
- Typed results (`ZelkovaResult`, agent verdict Pydantic models, evidence refs).
- Side effects: signed evidence writes, ASFF findings, Bedrock invocations.

**Integration**:
- Every exception is a domain exception from `adapters/src/sentinel_iq_adapters/errors.py`. Callers translate to their conservative-default failure mode.
- Adapters MUST NOT be aware of `DecisionRecord`, `SpecialistVerdict`, etc. except at the Security Hub mapping layer where an ASFF translation is required.

---

## 7. Acceptance Criteria and Validation Commands

- `pytest adapters/tests` passes with ≥ 90 percent line coverage.
- Property-based sanitizer tests run at least 1,000 examples with zero counterexamples.
- Prompt-injection smoke suite (20 payloads) passes: every payload either produces a forbidden-pattern rejection at ingest or a Guardrail intervention at output.
- `ruff check adapters/` clean.
- `mypy --strict adapters/src` clean.
- All boto3 calls covered by `moto` in unit tests; live smoke tests only in an integration test suite that requires explicit opt-in.
