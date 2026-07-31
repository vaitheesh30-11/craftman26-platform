# ADR 0021 — Frontend phase-00: hand-mirrored response types instead of full OpenAPI codegen

## Status
Accepted.

## Context
`docs/EXECUTION_PLAN.txt` §7 asks the frontend to generate a typed backend
client from `backend/openapi.golden.json` via `openapi-typescript`
(phase-00 §2's `lib/api-client.ts`). `backend`'s routers all return
`envelope.ok(model)` (`backend/src/iam_sentinel_backend/envelope.py`),
which wraps an already-validated Pydantic model in a plain
`dict[str, Any]` at the route boundary — honest FastAPI behavior, but it
means every route's OpenAPI response schema is a bare `{}`.
`openapi-typescript` therefore has nothing to generate a response type
from; it can only generate accurate *request* body types.

## Decision
`lib/api-types.gen.ts` (generated, checked in, drift-checked by
`scripts/check-api-drift.mjs`) is kept as the source of truth for every
request body type. `lib/api-types.ts` hand-mirrors the response shapes
directly from `backend/src/iam_sentinel_backend/schemas/*.py`,
field-for-field, importing `components` from the generated file rather
than duplicating request types.

## Consequences
- Response types will silently drift if a backend schema changes without
  a corresponding manual update to `lib/api-types.ts` — no compiler or CI
  check catches this today.
- Rejected alternative: changing `envelope.ok()` to return the model
  directly (not wrapped in a bare dict) so FastAPI's own response_model
  machinery could populate the OpenAPI schema. Rejected because that is a
  backend-shape change motivated purely by a frontend codegen convenience,
  and `backend` phase-01 already shipped and is tagged
  `phase/backend-rest-done` — reopening it here is out of scope for a
  frontend-only phase.
- Whoever next touches a `backend/schemas/*.py` file that has a
  `lib/api-types.ts` mirror should update both in the same change. A
  future phase could close the drift gap for real by adding a
  contract test that imports both and asserts field-name parity (out of
  scope for phase-00's 2-day budget).
