# backend/docs — Phase Roadmap

Five phases. Phase-00 first; the rest can execute in parallel.

| Phase | File                                | Delivers                                                    |
|-------|-------------------------------------|-------------------------------------------------------------|
| 00    | `phase-00-backend-foundations.txt`  | FastAPI factory, auth middleware, adapter deps, error envelopes |
| 01    | `phase-01-rest-api.txt`             | All 16 REST endpoints (chat, findings, decisions, ops, etc.)|
| 02    | `phase-02-websocket-stream.txt`     | $connect / $default / $disconnect + Prime stream fan-out    |
| 03    | `phase-03-approval-workflow.txt`    | Approve/reject with Zelkova pre-check + post-check          |
| 04    | `phase-04-audit-reports.txt`        | Read paths over decisions, findings, reports, faults        |

## Branches

- `feat/backend-foundation`
- `feat/backend-rest`
- `feat/backend-websocket`
- `feat/backend-approval`
- `feat/backend-audit`
