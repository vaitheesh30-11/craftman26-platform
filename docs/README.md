# Sentinel-IQ v8 — Documentation Index

Central specifications, contracts, and delivery matrix. All authoritative design lives in this directory.

## Read Order

1. `../SYSTEM_STATE.md` — universal AI project memory. Read first. Never skip.
2. `ARCHITECTURE.md` — system design blueprint (dual-path decision engine, Zelkova, XML fencing, ResultPath aggregation).
3. `DATA_CONTRACTS.md` — field-level specification of `DiffArtifact`, `SpecialistVerdict`, `DecisionRecord`, `IntentBaseline`.
4. `API_SPEC.md` — REST + WebSocket contract between `backend/` and `frontend/`.
5. `EPICS_AND_STORIES.md` — GitHub-Issue-ready delivery matrix (7 epics, 43 stories).

## Owning Documents

| Question | Look here |
|---|---|
| What is Sentinel-IQ? | `../SYSTEM_STATE.md` section 1 |
| How is a drift decided? | `ARCHITECTURE.md` section 1 |
| What HTTP endpoints exist? | `API_SPEC.md` |
| What does an event on the WebSocket look like? | `API_SPEC.md` section 7 |
| What fields does `DecisionRecord` have? | `DATA_CONTRACTS.md` section 3 |
| What is the byte limit on an SCP? | `../SYSTEM_STATE.md` section 2 |
| What must I do next? | `EPICS_AND_STORIES.md` |

## Change Discipline

Any change to `DATA_CONTRACTS.md` or `API_SPEC.md` MUST be accompanied by an update to `EPICS_AND_STORIES.md` if the change affects existing story acceptance criteria, and to the affected module `README.md` if it changes the Codex-executable instructions.
