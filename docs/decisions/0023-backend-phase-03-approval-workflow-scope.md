# ADR 0023 — backend phase-03: approval workflow scope

Status: accepted
Date: 2026-07-31

## Context

`backend/docs/phase-03-approval-workflow.txt` §2 asks for a real Step
Functions Standard state machine, `SentinelApprovalApply` (ASL definition +
CDK wiring: `ZelkovaPreCheck` -> `Apply` -> `Wait 15s` -> `ZelkovaPostCheck`
-> `Rollback`/success), to actually run a proposed `RemediationPlan`. That
state machine is `aws-infra`'s deliverable per this repo's established
module boundary (CDK lives in `aws-infra/`, `backend/` only calls AWS
through `adapters/`), and `aws-infra` has not built it yet. This is the
same shape of gap ADR 0017 (`functions/backend_api`'s packaging shim) and
ADR 0018 decision 1 (`RouterBridgeService` against `functions/router`)
already resolved: build the caller against the documented contract, defer
the callee, and make the deferral degrade cleanly rather than crash.

## Decisions

### 1. `routers/approvals.py` + `services/approval_service.py` call a documented `states:StartSyncExecution` contract; `SentinelApprovalApply` itself is not built

`ApprovalService.approve()` implements phase-03 §3 steps 1-3 exactly: load
and validate the decision/remediation, compute the idempotency key, then
call `states:StartSyncExecution` and return its output. It does not call
Zelkova, IAM, Organizations, CloudTrail, or Access Analyzer directly — §4's
state machine (`ZelkovaPreCheck`/`Apply`/`Wait`/`ZelkovaPostCheck`/
`Rollback`) owns all of that, and none of it exists yet. A "Zelkova
pre-check rejection" from the caller's point of view is simply the state
machine's synchronous output reporting `state="REJECTED"` — a valid
business outcome `ApprovalService` passes through as-is (HTTP 200, not an
error), never something backend evaluates itself. This is directly
testable today with a mocked `StepFunctionsClient`, and needs no change
once the real state machine ships — the "callee" is `aws-infra`'s to swap
in.

### 2. `StepFunctionsClient` (new, `adapters/compute/step_functions_client.py`) and its ARN are resolved from SSM, not hardcoded, per ADR 0017's shim precedent

The state machine's ARN comes from `/sentinel/{stage}/approval/
state-machine-arn` (`BackendSettings.approval_state_machine_ssm_param`),
read through a new minimal `SsmParameterClient` (`adapters/ssm/params.py`,
5-minute in-process cache). When that parameter has no value —
true today, since `SentinelApprovalApply` isn't deployed —
`ApprovalService.approve()` returns a deterministic `503
APPROVAL_STATE_MACHINE_NOT_CONFIGURED` *before* claiming any idempotency
key or touching DynamoDB, the same "clear error code, not a crash" contract
`functions/backend_api/handler.py`'s `502 BACKEND_NOT_PACKAGED` shim set.
Whoever builds the state machine publishes the SSM parameter as part of
that phase; no backend redeploy or code change is needed once it exists.

### 3. Idempotency extends `SentinelIdempotency`/`IdempotencyClient`, not a new table

`docs/DATA_CONTRACTS.md` and this table's existing `IdempotencyClient`
(adapters phase-01, `claim`/`already_claimed`) only ever needed a bare
claim marker for Prime's post-turn Lambda. Phase-03 §2 step 2 needs more: a
claim that also remembers *what* was claimed, so a replayed
`POST /approve` with the same `decision_id` + `remediation_index` +
`principal_arn` (`key = sha256(...)`) and the same request body
(`input_hash`, RFC 8785-canonicalized) returns the prior result instead of
re-invoking the state machine, while a same-key-different-body replay is a
`409 IDEMPOTENCY_KEY_CONFLICT` rather than silently returning a stale
answer. Added `claim_for_result`/`get_record`/`store_result` to the
existing `IdempotencyClient` (same table, same conditional-put pattern as
`claim`) rather than a second table or client — this is the identical
"add on-demand, following the established pattern" precedent ADR 0006 set
for adding table clients.

For a synchronous `StartSyncExecution` call there is effectively no window
where a *different* request observes `status="RUNNING"` from a completed
peer — the call blocks until the state machine finishes. This code path
(`APPROVAL_IN_PROGRESS`, `409`) exists for the genuine concurrent-request
race and is unit-tested for the claim-conflict branch, but not for an
actual in-flight-for-seconds scenario, which needs a real (or Step
Functions Local) execution to observe.

### 4. `EvidenceKind` grows one value, `"approval_decision"`, for the reject path

Phase-03 §5 requires `POST /reject` to "emit an evidence blob"; none of
`adapters/evidence/keys.py`'s six existing kinds
(`specialist_input`/`specialist_output`/`zelkova_invocation`/
`policy_mutation`/`guardrail_intervention`/`repair_action`/`fault`)
describes "a human rejected a proposed remediation" — `policy_mutation`
implies a mutation happened, which reject explicitly does not do. Added
`"approval_decision"` as a seventh literal, the same "extend the enum
on-demand" precedent the existing `repair_action`/`fault` entries already
set for phases after phase-04 first authored this file.

### 5. Found and documented, not fixed: `agents/prime/post_turn.py::DecisionsClient.put()` does not persist `remediations_proposed` or `specialist_verdicts`

Reading `post_turn.py` (backend phase-01 §4 step 5's own documented
precedent for "read the actual producer before guessing its contract",
ADR 0018 decision 5) shows `PrimePostTurnProcessor.process()`'s call to
`self._decisions.put({...})` only ever writes `decision_id`,
`correlation_id`, `principal`, `status`, `narrative`, `decided_at` — not
`remediations_proposed`, `remediations_applied`, or `specialist_verdicts`,
even though `DecisionRecord` (`docs/DATA_CONTRACTS.md` §7) carries all
three and `compose()`'s in-memory object has them. This means
`GET /decisions/{id}` today returns those fields empty, and — more to this
phase's point — a live `POST /approve` against a real deployed stack would
404 with `REMEDIATION_NOT_FOUND` for every decision, not because of
anything phase-03 does wrong, but because the row it reads never had a
remediation to find. This is an `agents/` module bug, out of this phase's
boundary to fix (`backend/` doesn't own `post_turn.py`) — flagged here
rather than silently worked around. `ApprovalService._load_transitionable_
remediation` treats a missing/short `remediations_proposed` as a clean
`404 REMEDIATION_NOT_FOUND`, not an `IndexError`, so this gap fails
predictably today and needs no change in `backend/` once agents/ fixes it.

### 6. On approve success, the state machine's outcome maps to a decision-status transition; on `REJECTED` (pre-check), the decision is left untouched

`SUCCEEDED` -> `AUTO_REMEDIATED` (matches ADR 0018 decision 4's existing
convention); `ROLLED_BACK` -> `ESCALATED` (a rollback fired, which the
spec's own risk table §8 says needs a human, not a silent close) — this
mapping is this phase's own judgment call, not stated verbatim in the spec,
recorded here rather than left implicit in code. `REJECTED` (Zelkova
pre-check failed inside the state machine) leaves the decision's status
and `remediations_proposed` unchanged, so the caller can retry a different
remediation index or re-approve after fixing the underlying policy.

## Consequences

1. `SentinelApprovalApply`'s ASL definition, its IAM role (§5), and the
   `Apply`/`Rollback` appliers per `remediation.action` are entirely
   unbuilt. `docs/EXECUTION_STATE.txt` should track this as an open item
   for whichever `aws-infra` phase claims it, the same way ADR 0017's
   `backend_api` packaging gap is tracked.
2. §6's Test Plan "Integration (Step Functions Local + moto)" and
   "Property: post-check always runs after every apply" are deferred with
   the state machine itself — nothing in `backend/` can exercise a state
   machine that isn't deployed. §7's acceptance criteria ("Zelkova
   pre-check gates every apply", "Rollback fires and succeeds") are
   contract-level today (verified by `ApprovalService`'s pass-through of a
   mocked `state`), not behavior-level.
3. Decision 5's persistence gap means every approve/reject call against a
   real deployed stack 404s until `agents/prime/post_turn.py` is fixed to
   write `remediations_proposed`. Backend phase-03 is code-complete against
   the documented contract; it is not yet end-to-end live-verifiable, the
   same class of deferral ADR 0018's own §Deferred section already
   accepted for this phase's predecessor.
4. `APPROVAL_IN_PROGRESS`'s concurrent-request race is exercised only at
   the `claim_for_result` boundary in tests, not with real concurrency.
