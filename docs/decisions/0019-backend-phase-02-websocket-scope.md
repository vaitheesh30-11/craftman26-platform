# ADR 0019 — backend phase-02: WebSocket streaming scope

Status: accepted
Date: 2026-07-31

## Context

`backend/docs/phase-02-websocket-stream.txt` asks for three Lambdas
(`src/iam_sentinel_backend/ws/{connect,default,disconnect}.py`) plus a
"stream fan-out service" and the `SentinelConnections` table. `aws-infra`
phase-07 (sprint step 20, already merged) built the WebSocket API, the
`SentinelConnections` table, and three placeholder Lambdas
(`aws-infra/functions/ws_connect|ws_default|ws_disconnect/handler.py`) whose
own docstrings explicitly defer the real logic to this phase — `ws_default`'s
says so in as many words: "`InvokeAgentWithResponseStream` + chunk-by-chunk
`PostToConnection` is `backend` phase-02's deliverable... not this CDK-only
phase's." Three genuine scope decisions follow.

## Decisions

### 1. Real logic lands in `backend/`; `aws-infra`'s placeholder Lambdas are left wired but unswapped

`aws-infra/tests/unit/test_ws_handlers.py` locks in the phase-07 placeholder
behavior (`ws_connect`/`ws_disconnect` persist/delete via raw `boto3`;
`ws_default` acks a frame) as passing tests on `main`. Swapping those
`handler.py` files to import `iam_sentinel_backend` would hit the same
Lambda dependency-bundling gap ADR 0011/0015/0017 already flagged
(`functions/backend_api/handler.py` degrades to a deterministic 502 for the
identical reason) — `iam_sentinel_backend` is not on any deployed Lambda's
`sys.path` yet. Rather than either (a) reimplementing this phase's logic a
second time as raw-`boto3` `aws-infra` Lambda code, duplicating business
logic and drifting from it immediately, or (b) breaking phase-07's own
passing test suite to wire in an import that fails at runtime today, this
phase builds the real, fully tested logic in `backend/src/
iam_sentinel_backend/ws/` — each module exports both the pure, DI-friendly
function (`handle_connect`/`handle_default`/`handle_disconnect`, unit-tested
with mocked adapters clients) and a `handler(event, context)` Lambda
entrypoint that resolves real singletons via `deps.py`. Whoever solves the
Lambda-bundling gap should point `aws-infra/functions/ws_*` at these
`handler()` functions and delete the placeholder `boto3` bodies (and their
now-superseded test file) in the same change — do not layer a second shim
on top; retire the placeholder.

### 2. `ConnectionsClient` writes the phase-02 §2 attribute set, not phase-07's ad hoc one

`aws-infra`'s `ws_connect` stub writes `principal`/`auth_kind`/`connected_at`
with a 4h TTL it invented for its own acknowledgement purpose; phase-02 §2
specifies `principal`/`session_id`/`connected_at` with a 1h TTL.
`iam_sentinel_adapters.ddb.connections.ConnectionsClient` (new, following
ADR 0006/0018's "add a table client on demand" precedent) writes exactly
phase-02's attribute set against the same `connection_id`-keyed table
`aws-infra` phase-07 already provisions — DynamoDB's schemaless non-key
attributes mean both writers can coexist on the same table without a
migration; whichever Lambda actually runs in production is authoritative,
and decision 1 above is what determines that.

### 3. `StreamFanoutService` does not parse Prime's completion; it polls `SentinelDecisions` the same way `ChatService` does

Per the same reasoning ADR 0018 decision 5 already established for
`backend` phase-01's `POST /agent/chat`: Prime's specialist fan-out and
`DecisionRecord` synthesis happen inside Bedrock and the already-built
post-turn Lambda. Once `invoke_agent_stream`'s final chunk arrives,
`StreamFanoutService._poll_for_decision` polls `SentinelDecisions` with a
tight, WebSocket-appropriate budget (`ws_result_poll_budget_seconds`, default
5s vs. REST's 25s) rather than re-deriving structured findings from raw
completion text.

### Deferred, needs a live AWS account

- §7's "Bedrock progress chunks reach the client in < 300 ms after emission"
  — no deployed `SentinelStream` + Prime alias to measure against; the
  ~50 msg/s rate limiter and 128 KB frame cap are implemented and unit-tested
  as design properties (`StreamFanoutService._truncate`, the
  `next_allowed_send` gate), not measured.
- §6's LocalStack API Gateway integration test (a live WebSocket round-trip)
  and the 10 Hz connect/disconnect leak test — both need a running API
  Gateway WebSocket endpoint; `handle_connect`/`handle_disconnect` are unit-
  tested against mocked `ConnectionsClient` instead.
- Decision 1's actual Lambda rewiring, blocked on the pre-existing bundling
  gap.

## Consequences

1. Whoever closes the Lambda-bundling gap must repoint `aws-infra/functions/
   ws_connect|ws_default|ws_disconnect/handler.py` at `iam_sentinel_backend.
   ws.{connect,default,disconnect}.handler` and delete
   `aws-infra/tests/unit/test_ws_handlers.py`'s placeholder assertions in
   the same change, not layer a fourth shim on top of the third.
2. `SentinelConnections`' TTL as actually enforced by DynamoDB is whichever
   writer runs — 4h from the still-deployed placeholder today, 1h once
   decision 1 is resolved. Not a correctness issue (both delete on
   disconnect too), but worth remembering when reasoning about "how long do
   idle rows live."
3. `docs/EXECUTION_STATE.txt`'s sprint step 23 (`aws-infra` phase-06,
   EventBridge + alarms) is unaffected by this ADR; it does not touch
   `SentinelStream`.
