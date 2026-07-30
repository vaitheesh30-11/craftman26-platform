# ADR 0006 — adapters phase-05: base client + representative table clients, not all 14

Status: accepted
Date: 2026-07-30

## Context

`adapters/docs/phase-05-ddb-adapter.txt` asks for one typed client module
per table (14, per ADR 0005) plus a `MemoryClient` combining DDB and
OpenSearch Serverless. No specialist Lambda exists yet to consume any of
these clients — Sentinel Prime lands in agents phase-01 (sprint step 16,
Wave 3), and the first specialist (F1 PassRole Cartographer) right after
it. Fully typing all 14 tables' clients now means guessing at exact field
shapes and query patterns before any real caller exists to validate them
against — exactly the kind of premature, ahead-of-need design the
project's own engineering guidance warns against.

The `FindingsClient.put(self, finding: Finding) -> None` signature in the
spec also raises a module-boundary question: `Finding` is agents'
Pydantic model (`agents/src/iam_sentinel_agents/contracts/finding.py`),
and `adapters/README.md` §1 says adapters "Never imports from agents/".

## Decision

- Build the reusable base (`ddb/base.py`'s `DynamoDbHelper`): marshal/
  unmarshal, `Policy.AGGRESSIVE` retry, circuit-breaker integration
  (reusing phase-00's `BreakerAccessor`), and EMF read/write metrics. This
  is the actual "real logic" of the phase — every table client is a thin
  wrapper over it.
- Every client method takes and returns plain `dict[str, object]` (or a
  small adapters-local dataclass for return-shape clarity), never an
  agents Pydantic model — callers in `agents/` construct their own typed
  model, call `.model_dump()`, and pass the dict through. This satisfies
  the module boundary without inventing a second, potentially-drifting
  copy of `Finding`, `EpisodicMemory`, etc.
- Implement three representative table clients covering the three
  distinct access patterns in the inventory: `FindingsClient` (composite
  PK/SK + 2 GSIs, the one the spec gives a full interface for),
  `DecisionsInFlightClient` (PK-only + TTL, the simplest shape), and
  `MemoryClient`'s episodic path (DDB write + an OSS write queued via SQS
  for async indexing, per phase-05 §6 step 3 — the DDB half is real; the
  OSS k-NN read half is a documented interface stub, deferred with the
  rest of OpenSearch Serverless verification per ADR 0005).
  `SentinelBreakers` and `SentinelBudget` already have working clients
  from adapters phase-00 (`circuit_breaker.py`, `cost_meter.py`) — not
  duplicated here.
- The remaining 9 table clients (`Decisions`, `MemorySemantic`,
  `MemoryProcedural`, `Policies`, `SLRs`, `Revocations`, `Faults`,
  `Divergence`, `Idempotency`) are mechanical repeats of the same
  `DynamoDbHelper` pattern with a different table name and key shape.
  Add each on-demand when the specialist or backend phase that actually
  needs it lands, rather than guessing its query shape now.

## Consequences

- Acceptance criterion "all 13/14 tables covered with typed helpers" is
  not met in full. Tracked in `docs/EXECUTION_STATE.txt` as an open item,
  not silently dropped — whoever builds agents phase-02 (F1, the first
  real consumer) should add the specific table clients it needs following
  this phase's established `DynamoDbHelper` pattern.
- `MemoryClient.recall_episodic`'s vector search path cannot be verified
  without a deployed OpenSearch Serverless collection — same deferred-
  live-account status as the rest of ADR 0005.
