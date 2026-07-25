# backend/ — FastAPI + WebSocket Management API

FastAPI service that exposes the REST and WebSocket contract defined in `docs/API_SPEC.md`. Reads from the S3 Object Lock evidence lake and DynamoDB. Never writes AWS state directly (Executor Lambda owns writes). Resumes Step Functions Standard Workflows for approval callbacks.

---

## 1. Module Purpose and System Boundaries

**Purpose**. The read-and-approve surface for humans and the Frontend. Every REST endpoint and every WebSocket event lives here.

**In scope**:
- REST endpoints defined in `docs/API_SPEC.md` sections 1-6.
- WebSocket gateway at `/ws/drift` per section 7.
- Cognito-backed authentication.
- CORS, rate limiting, error envelope.
- Step Functions callback token resume for approvals.

**Out of scope**:
- Any Bedrock invocation (agents own this).
- Any IAM / SCP mutation (Executor Lambda under permission boundary).
- Any Zelkova invocation (`adapters/` owns this; backend can invoke read-only queries for `POST /baselines` regression checks by delegating to a Zelkova Lambda through `adapters/`).

**Boundaries**:
- Input: HTTPS from `frontend/` (or third-party integrators).
- Output: reads from evidence lake, resumes Step Functions, publishes real-time frames to WebSocket connections.
- Never imports from `agents/` or `frontend/`.

---

## 2. Files and Directory Tree to Generate

```
backend/
├── pyproject.toml
├── README.md                          (this file)
├── src/
│   └── sentinel_iq_api/
│       ├── __init__.py
│       ├── main.py                    App factory + Lambda web adapter entrypoint
│       ├── settings.py                Pydantic Settings
│       ├── auth.py                    Cognito JWT verification + IAM SigV4 fallback
│       ├── middleware/
│       │   ├── __init__.py
│       │   ├── request_id.py
│       │   ├── rate_limit.py
│       │   ├── error_handler.py
│       │   └── cors.py
│       ├── routes/
│       │   ├── __init__.py
│       │   ├── drift.py               GET /drift, /drift/{id}
│       │   ├── decisions.py           GET /decisions, POST /decisions/{id}/approve
│       │   └── baselines.py           GET, POST /baselines
│       ├── ws/
│       │   ├── __init__.py
│       │   ├── router.py              /ws/drift entry
│       │   ├── connection_manager.py  Connection registry backed by DynamoDB
│       │   ├── keepalive.py           30 s server-ping / 10 s pong deadline
│       │   └── event_frames.py        Typed frame factories
│       ├── clients/
│       │   ├── __init__.py
│       │   ├── evidence_lake.py       S3 Object Lock reader
│       │   ├── ddb_decisions.py       DynamoDB decision index reader
│       │   ├── step_functions.py      Standard Workflow callback resumer
│       │   └── zelkova.py             Thin wrapper delegating to adapters/zelkova
│       └── schemas.py                 Import mirrors of docs/DATA_CONTRACTS.md
└── tests/
    ├── unit/
    │   ├── test_drift_routes.py
    │   ├── test_decisions_routes.py
    │   ├── test_baselines_routes.py
    │   ├── test_auth.py
    │   ├── test_rate_limit.py
    │   └── test_error_envelope.py
    ├── integration/
    │   ├── test_ws_gateway.py
    │   └── test_approval_flow.py
    └── conftest.py
```

---

## 3. Tech Stack and Recommended Libraries

- Python 3.11+.
- FastAPI 0.115+.
- Pydantic v2 (schemas mirror `docs/DATA_CONTRACTS.md`).
- Uvicorn (local) + Mangum (Lambda).
- `python-jose` for Cognito JWT verification.
- `boto3` for AWS SDK.
- `redis` (or DynamoDB-backed) for rate limiting.
- API Gateway WebSocket + Lambda for `/ws/drift` (backend is Lambda-first; a long-running WebSocket server is out of scope).
- `pytest` + `pytest-asyncio` + `httpx` for tests.
- `moto` for AWS mocking in unit tests.

---

## 4. Step-by-Step Implementation Instructions

### 4.1 App factory
1. `main.py` exposes `create_app() -> FastAPI` and `handler = Mangum(app)` for Lambda.
2. Wire middleware in this order: CORS → request_id → rate_limit → error_handler → routes.
3. Register OpenAPI metadata pinning `version = "1.0"` and pointing to `docs/API_SPEC.md`.

### 4.2 Auth
1. `auth.py` exposes `require_user(request) -> Principal` that:
   - Decodes Cognito JWT via JWKS URL from settings.
   - Falls back to SigV4 verification for machine-to-machine calls.
   - Raises `HTTPException(401, envelope=Unauthenticated)` on failure.
2. Every route uses `Depends(require_user)`. Roles are extracted from Cognito groups.

### 4.3 REST routes
1. `routes/drift.py`:
   - `GET /api/v1/drift` — cursor pagination against DynamoDB GSI keyed by `produced_at`.
   - `GET /api/v1/drift/{id}` — fetches DiffArtifact + all specialist verdicts + latest DecisionRecord + Zelkova pre/post + ActionRecord from evidence lake.
2. `routes/decisions.py`:
   - `GET /api/v1/decisions` — cursor pagination with filters.
   - `POST /api/v1/decisions/{id}/approve` — validates two-signer for Tier-0, verifies callback token, resumes Step Functions Standard via `clients/step_functions.py`, records approver identity.
3. `routes/baselines.py`:
   - `GET /api/v1/baselines` — reads active baseline pointer from DynamoDB, resolves S3 object.
   - `POST /api/v1/baselines` — verifies KMS signature, kicks off async Zelkova regression check, returns 202 with a pending state.

### 4.4 WebSocket gateway (`ws/`)
1. API Gateway WebSocket route selection expression: `$request.body.action`.
2. `$connect`: verify Cognito JWT from query string OR the `Authorization` header via a custom Lambda authorizer.
3. `$default`: parse JSON, route on `action` field (`SUBSCRIBE`, `UNSUBSCRIBE`, `PONG`).
4. `$disconnect`: remove from `connection_manager` DynamoDB table.
5. Server-initiated events (`DRIFT_DETECTED`, `DECISION_EMITTED`, `REMEDIATION_COMPLETE`, `VERIFICATION_FAILED`) are pushed by a fan-out Lambda that reads SNS topics populated by the Normalizer, Council, and Executor.
6. Keepalive Lambda runs every 30 s and posts a `PING` frame; if a `PONG` is not observed within 10 s, close code `4408`.

### 4.5 Error envelope
1. `middleware/error_handler.py` catches all exceptions and produces the envelope from `docs/API_SPEC.md` section 8.
2. Every `HTTPException` MUST have a `code` field mapped to a stable client-visible identifier.

### 4.6 Rate limiting
1. Sliding window rate limiter keyed by `(principal_id, endpoint_group)`.
2. Storage: DynamoDB with atomic increment via `UpdateItem` + conditional expression.
3. Emits `Retry-After` header on breach.

---

## 5. Exact Codex Prompts

**Prompt A — App skeleton**
> Read `docs/API_SPEC.md` and `docs/DATA_CONTRACTS.md`. Generate `backend/src/sentinel_iq_api/main.py`, `settings.py`, `middleware/*`, and `schemas.py`. Wire CORS, request-id, error envelope, and rate limiting. Include a `/healthz` route. Use FastAPI 0.115 idioms with lifespan events.

**Prompt B — Auth**
> Generate `backend/src/sentinel_iq_api/auth.py` supporting Cognito JWT (JWKS URL from settings) and SigV4 fallback. Extract user roles from the Cognito `cognito:groups` claim. Every REST route uses `Depends(require_user)`. Include unit tests using cached JWKS fixtures.

**Prompt C — Drift routes**
> Generate `backend/src/sentinel_iq_api/routes/drift.py` and the `evidence_lake.py` + `ddb_decisions.py` clients. Implement `GET /api/v1/drift` cursor pagination and `GET /api/v1/drift/{id}` deep dive per `docs/API_SPEC.md` sections 1-2. Include unit tests with `moto` for S3 and DynamoDB.

**Prompt D — Decisions and approval**
> Generate `backend/src/sentinel_iq_api/routes/decisions.py` and `clients/step_functions.py`. Implement approval callback resume with two-signer corroboration for Tier-0 resources per `docs/API_SPEC.md` section 4. Idempotency required on retries. Include integration tests with `moto` and a Step Functions mock.

**Prompt E — Baselines**
> Generate `backend/src/sentinel_iq_api/routes/baselines.py`. `GET` reads from S3 via `evidence_lake.py`. `POST` verifies KMS signature, kicks off async Zelkova regression check via `clients/zelkova.py`, returns 202 with pending state.

**Prompt F — WebSocket gateway**
> Read `docs/API_SPEC.md` section 7. Generate `backend/src/sentinel_iq_api/ws/*`. Implement API Gateway WebSocket route handlers (`$connect`, `$default`, `$disconnect`), connection manager backed by DynamoDB, keepalive Lambda, and typed event-frame factories for the four server-initiated frames. Integration test using `websockets` client against a mocked API Gateway.

---

## 6. Inputs, Outputs, and Integration Boundaries

**Inputs**:
- REST requests from `frontend/` and integrators.
- WebSocket connections from `frontend/`.
- SNS notifications from Normalizer, Council, Executor for real-time fan-out.

**Outputs**:
- REST responses per `docs/API_SPEC.md`.
- WebSocket frames per section 7.
- Step Functions `SendTaskSuccess` / `SendTaskFailure` for approval callbacks.
- Evidence lake reads only. No writes.

**Integration**:
- Backend MUST NOT invoke Bedrock, IAM writes, Organizations mutations, or Executor actions.
- All reads MUST validate against `docs/DATA_CONTRACTS.md`.

---

## 7. Acceptance Criteria and Validation Commands

- `pytest backend/tests` passes with ≥ 85 percent line coverage.
- `ruff check backend/` clean.
- `mypy --strict backend/src` clean.
- OpenAPI spec at `/openapi.json` matches `docs/API_SPEC.md` (paths, methods, response schemas).
- Load test: 100 RPS sustained on `GET /api/v1/drift` for 10 minutes with p95 < 300 ms.
- WebSocket: 1000 concurrent connections; server keepalive fires every 30 s; disconnect on missed pong.
