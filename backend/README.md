# backend/ — Management API for IAM Sentinel

The user-facing and machine-facing HTTP surface. Serves the REST endpoints defined in `aws-infra/docs/phase-07-api-stack.txt §3`, streams Prime turns over WebSocket, and manages remediation approval flows.

Authoritative canon: `SYSTEM_STATE.md`, `docs/ARCHITECTURE.md`, `docs/AGENTIC_DESIGN.md`, `docs/DATA_CONTRACTS.md`, `aws-infra/docs/phase-07-api-stack.txt`.

---

## 1. Module Purpose and System Boundaries

**Purpose.** Terminate every REST + WebSocket request; auth, rate-limit, translate to Bedrock InvokeAgent (streaming or non-streaming), or to a fast-path Lambda via the router; enforce approval-workflow safety (Zelkova pre-check gate); read data plane for findings/decisions.

**In scope.**
- FastAPI app (Mangum-adapted) hosted on Lambda behind API Gateway.
- WebSocket handler Lambda (separate function) using API Gateway Management API to push chunks.
- Auth middleware (Cognito JWT + IAM SigV4 fallback).
- Domain services: `chat`, `router_bridge`, `findings`, `decisions`, `approvals`, `reports`, `operations`.
- Request/response schemas mirroring `docs/DATA_CONTRACTS.md`.

**Out of scope.**
- Any AWS provisioning (owned by `aws-infra/`).
- Any tool implementation (owned by `agents/tools/`).
- Any client-side rendering (owned by `frontend/`).

**Boundaries.**
- Consumes: `adapters/` (Bedrock, DDB, evidence). Never uses raw boto3.
- Never imports from `agents/tools/`. Speaks to specialists only via Prime or via the router-bridge.

---

## 2. Directory Tree

```
backend/
├── README.md                       this file
├── pyproject.toml                  uv-managed, Python 3.12
├── docs/
│   ├── README.md                   phase index
│   ├── phase-00-backend-foundations.txt
│   ├── phase-01-rest-api.txt
│   ├── phase-02-websocket-stream.txt
│   ├── phase-03-approval-workflow.txt
│   └── phase-04-audit-reports.txt
├── src/
│   └── iam_sentinel_backend/
│       ├── __init__.py
│       ├── app.py                  FastAPI factory + Mangum handler
│       ├── settings.py
│       ├── deps.py                 dependencies (auth, adapter clients, correlation_id)
│       ├── auth/
│       │   ├── cognito.py
│       │   ├── sigv4.py
│       │   └── breakglass.py       validates BreakGlass session tag
│       ├── routers/
│       │   ├── chat.py
│       │   ├── findings.py
│       │   ├── decisions.py
│       │   ├── approvals.py
│       │   ├── reports.py
│       │   ├── operations.py
│       │   └── router_bridge.py    fast-path bridges (F1/F2/F3/F4/F7/F8)
│       ├── services/
│       │   ├── chat_service.py     Bedrock InvokeAgent orchestration
│       │   ├── stream_service.py   WebSocket stream fan-out
│       │   ├── approval_service.py Zelkova pre-check + apply
│       │   └── report_service.py
│       ├── ws/
│       │   ├── connect.py
│       │   ├── default.py
│       │   └── disconnect.py
│       └── errors.py               FastAPI exception handlers → JSON envelopes
└── tests/
    ├── unit/
    ├── integration/                LocalStack + moto
    └── contract/
```

---

## 3. Tech Stack

- Python 3.12.
- `fastapi==0.115.0` + `mangum==0.19` (Lambda + API Gateway adapter).
- `pydantic==2.9.2`, `pydantic-settings==2.5.2`.
- `aws-lambda-powertools[all]==2.42.0`.
- `httpx==0.27.2` for internal calls to fast-path Lambdas (via `lambda:InvokeFunction`, wrapped by the adapter).
- `pytest`, `moto[all]`, `httpx.MockTransport`, `pytest-asyncio`.

Forbidden: Django, Flask, generic API-frame-wrappers, LangChain/LangGraph.

---

## 4. Contract with Frontend

- All responses follow `docs/DATA_CONTRACTS.md`.
- Chat interactions stream over WebSocket `wss://<stage>.stream.sentinel.example` using a simple text protocol:
  - `event: progress` → `data: <one line>`.
  - `event: result` → `data: <DecisionRecord JSON>`.
  - `event: error` → `data: <{ code, message }>`.
- Non-chat REST responses are `application/json` with a common envelope: `{ ok: bool, data?: T, error?: { code, message, correlation_id } }`.

---

## 5. Non-Functional Requirements

- p95 REST latency ≤ 500 ms for read paths (findings/decisions list).
- p95 approval-apply latency ≤ 45 s (dominated by Zelkova post-check).
- Cold-start p95 ≤ 1.2 s (Powertools + FastAPI + Mangum).
- Auth failure returns 401 without leaking whether the resource exists.
- Every request emits a Powertools log line with correlation_id.

---

## 6. Acceptance Criteria (Module-Wide)

- [ ] `uv run ruff check backend/src` clean.
- [ ] `uv run mypy --strict backend/src` clean.
- [ ] `pytest backend/tests` ≥ 88% line coverage.
- [ ] OpenAPI schema exportable via `/openapi.json` on the deployed API.
- [ ] Golden-path e2e: `POST /agent/chat` returns a `DecisionRecord` in ≤ 25 s p95.
