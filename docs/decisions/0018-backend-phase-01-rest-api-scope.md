# ADR 0018 — backend phase-01: REST API scope

Status: accepted
Date: 2026-07-31

## Context

`backend/docs/phase-01-rest-api.txt` asks for all 16 REST endpoints from
`aws-infra/docs/phase-07-api-stack.txt §3`, built on phase-00's FastAPI
foundation. Several of this phase's callees (the fast-path router Lambda,
the self-healing fault writer, the weekly cost-report writer, phase-03's
approval-apply workflow) don't exist yet, and two DDB tables' actual key
shapes (confirmed against `aws-infra`'s `foundation_stack.py`, not the
older `docs/DATA_CONTRACTS.md §9` prose) don't support every filter the
spec's route table implies at O(1). Five genuine scope decisions follow;
all are architecture decisions made buildable-and-tested today, not
testing shortcuts.

## Decisions

### 1. Router Bridge is built against the documented contract; `functions/router` does not exist yet

`backend/docs/phase-01-rest-api.txt §5` specifies `router.execute(mode=
"fast", target=<Fx>, payload=<body>)` invoked via `lambda:InvokeFunction`.
That Lambda is agents phase-15's deliverable (Wave 8, sprint step 40) and
does not exist. `iam_sentinel_adapters.compute.lambda_client.
LambdaInvokeClient` (new) and `services/router_bridge_service.py` are
built and fully unit-tested against a mocked `LambdaInvokeClient` — the
same "build the caller before the callee exists" precedent as `aws-infra`
phase-08's cross-account StackSets (ADR 0014) and phase-07's `backend_api`
shim (ADR 0017). Invoking an undeployed function name in a real account
surfaces as `ResourceNotFoundException` → `ValidationError` → HTTP 400/502
through `router_bridge_service`, not a leaked 500.

### 2. Three adapters added on-demand, per ADR 0006's own precedent

`GET /operations/faults` and `GET /operations/cost/weekly` need table/
bucket clients ADR 0006 didn't scope in (it covered 3 of 14 tables; no
consumer needed the rest until now). Added, following the identical
patterns already established:
- `iam_sentinel_adapters.ddb.faults.FaultsClient` — key shape confirmed
  against `foundation_stack.py`'s `SentinelFaults` `_TableSpec`
  (`pk=correlation_id`, `sk=detected_at`, GSI `fault-class-index`).
  `FaultRecord`'s actual contract lives in `agents/docs/
  phase-17-self-healing.txt §10` (self-healing, not built); this client
  only stores/reads plain dicts, matching every other DDB client's module
  boundary with `agents/`.
- `iam_sentinel_adapters.s3.reports.ReportsClient` — read-only access to
  `SentinelReports/cost/*.json`; the report body's own schema is agents
  phase-16's contract to define.
- `iam_sentinel_adapters.compute.lambda_client.LambdaInvokeClient` — see
  decision 1.

`adapters/ddb/base.py` also grew `query_page`/`scan_page` (return
`LastEvaluatedKey` for `next_token` pagination; `scan_page` is the bounded
fallback for filter combinations no GSI covers) — additive, no existing
caller's signature changed.

### 3. No `decision_id`/`finding_id` GSI exists — single-record lookup by bare id is a bounded, not O(1), read

`GET /findings/{id}` and `GET /decisions/{id}` take a bare id with no
partition-key context. `SentinelFindings`'s two GSIs are keyed on
`severity` and `feature_id#status`; `SentinelDecisions`'s one GSI is keyed
on `correlation_id` — `decision_id` (`agents/src/iam_sentinel_agents/
prime/post_turn.py::decision_id = new_ulid()`) is a value independent of
`correlation_id`, confirmed by reading that Lambda's actual code rather
than trusting `DecisionsClient.put`'s pre-existing (and, it turns out,
inaccurate) docstring claim that they're related. `FindingsClient.
get_by_id`/`DecisionsClient.get_by_id` fall back to a bounded `Scan`
(10 pages of 100 items) filtered on the id — correct, not O(1). Callers
that already know the owning partition (`account_id`+`feature_id`, or
their own `principal`) get a real `Query` instead; the frontend's typical
flow (list, then open one item) already has that context from the list
response. Add a dedicated GSI in a future phase if bare-id lookup sees
real production traffic.

### 4. `POST /decisions/{id}/approve|reject` transitions status only; remediation application is phase-03's job

The route table itself says "see phase-03" for these two rows.
`services/approval_service.py` validates the decision exists, belongs to
the caller, and is in a transitionable state (`ANSWERED`/`ESCALATED`),
then writes the new `status` (`AUTO_REMEDIATED`/`REJECTED`) back to
`SentinelDecisions`. It does not invoke Zelkova's pre/post-check gate or
apply any `RemediationPlan` — that's `backend/docs/
phase-03-approval-workflow.txt`'s contract, and building a partial version
of it now would risk diverging from that phase's actual design.

### 5. `chat_service.ask_prime` does not parse Prime's completion into structured verdicts

Read `agents/src/iam_sentinel_agents/prime/supervisor.py` and
`prime/post_turn.py` before writing this: Prime's specialist fan-out and
`DecisionRecord` synthesis already happen inside Bedrock and a post-turn
Lambda that already exists and is already tested. Backend phase-01 §4's
steps 3-6 reduce to "invoke the agent, then poll `SentinelDecisions` for
what the post-turn Lambda writes" — re-parsing the raw completion text
into `Finding`/`SpecialistVerdict` objects here would duplicate business
logic `agents/` owns (and would require importing `agents.prime.
result_parser`, which the module boundary forbids — `backend/pyproject.
toml` depends only on `iam-sentinel-adapters`). `get_by_correlation_id`
(new, `DecisionsClient`) does the poll in O(1) via `SentinelDecisions`'
existing `correlation-index` GSI.

### Deferred, needs a live AWS account or a not-yet-built callee

- §9's "p95 latency ≤ 500 ms for read paths" — no deployed API Gateway +
  Lambda to benchmark against (same class of deferral as every prior
  `aws-infra` phase's live-account criteria).
- §9's "cross-principal read leakage impossible (property-tested)" —
  implemented as deny-by-default scoping (`findings_service.py`/
  `decisions_service.py`) with focused unit tests per the revised testing
  policy, not a Hypothesis property-fuzz run.
- `POST /agent/chat`'s real 25 s budget path — unverified against a real
  deployed Prime agent alias; unit-tested with a fast `chat_poll_budget_
  seconds` override and a mocked `LLMProvider`.
- `GET /monitor/shadow-violations`'s actual F6 read shape, and every other
  fast-path's `trusted_input` schema — owned by each specialist's own
  phase doc, most of which (F2-F8) aren't built. `schemas/router_bridge.py`
  keeps the request/response bodies as validated-but-open dicts rather
  than guessing those contracts ahead of their owning phases.

## Consequences

1. Whoever builds `functions/router` (agents phase-15) should re-verify
   `RouterBridgeService` against a real invocation once it's deployed —
   today's tests only prove the adapter's error-mapping and the service's
   request-shaping, not the callee's actual behavior.
2. Whoever builds agents phase-17 (self-healing) or phase-16 (cost
   guardrails) should confirm `FaultRecord`'s and the cost report's actual
   written shape matches `schemas/operations.py`'s loosely-typed models;
   both are intentionally tolerant (`extra="ignore"`) rather than guessed
   strict schemas.
3. `backend/docs/phase-03-approval-workflow.txt` inherits a working
   status-transition primitive (`ApprovalService._transition`) to build
   the Zelkova-gated apply flow on top of, not around.
