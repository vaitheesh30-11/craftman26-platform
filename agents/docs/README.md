# agents/docs — Phase-Scoped Delivery Roadmap

This directory holds one txt file per phase. Each phase is a self-contained sprint spec: any principal engineer should be able to pick it up cold and execute it in 1–3 days. Phase files supersede everything else in the module — if a phase file and a source file disagree, the phase file wins until amended.

## Phase Index

| Phase                             | File                                       | Owner assumption          | Depends on           |
|-----------------------------------|--------------------------------------------|---------------------------|----------------------|
| Foundations                       | `phase-00-foundations.txt`                 | 2 principal engineers     | –                    |
| Supervisor (Sentinel Prime)       | `phase-01-supervisor-agent.txt`            | 1 principal engineer      | phase-00             |
| F1 PassRole Cartographer          | `phase-02-passrole-cartographer.txt`       | 1 principal engineer      | phase-00, phase-01   |
| F2 Org Context Validator          | `phase-03-org-context-validator.txt`       | 1 principal engineer      | phase-00, phase-01   |
| F3 Data Event Enricher            | `phase-04-data-event-enricher.txt`         | 1 principal engineer      | phase-00, phase-01   |
| F4 SCP Impact Analyst             | `phase-05-scp-impact-analyst.txt`          | 1 principal engineer      | phase-00, phase-01   |
| F5 Session Terminator             | `phase-06-session-terminator.txt`          | 1 principal engineer      | phase-00, phase-01   |
| F6 Shadow Guard                   | `phase-07-shadow-guard.txt`                | 1 principal engineer      | phase-00, phase-01   |
| F7 Collision Resolver             | `phase-08-collision-resolver.txt`          | 1 principal engineer      | phase-00, phase-01, phase-05 (SCP eval engine) |
| F8 SLR Guardian                   | `phase-09-slr-guardian.txt`                | 1 principal engineer      | phase-00, phase-01   |
| RAG Knowledge Base                | `phase-10-rag-knowledge-base.txt`          | 1 principal engineer      | phase-00             |
| Guardrails & Safety Substrate     | `phase-11-guardrails-safety.txt`           | 1 principal engineer      | phase-00             |
| Observability & Evals             | `phase-12-observability-evals.txt`         | 1 principal engineer      | phase-00, phase-01   |
| Integration Tests                 | `phase-13-integration-tests.txt`           | 2 principal engineers     | all specialists      |
| Memory Fabric                     | `phase-14-memory-fabric.txt`               | 1 principal engineer      | phase-00             |
| Dual-Mode Execution               | `phase-15-dual-mode-execution.txt`         | 1 principal engineer      | phase-01, all specialists |
| Cost Guardrails                   | `phase-16-cost-guardrails.txt`             | 1 principal engineer      | phase-00, phase-01   |
| Self-Healing                      | `phase-17-self-healing.txt`                | 1 principal engineer      | phase-00, phase-01, phase-11 |

## Execution Order (Recommended)

1. **Week 1.** `phase-00`, `phase-10`, `phase-11` (foundations and the safety substrate).
2. **Week 2.** `phase-01` (supervisor). Parallel: `phase-12` (observability) once phase-01 has an alias.
3. **Weeks 2–3.** Eight specialists (`phase-02..09`) executed in parallel by eight streams. `phase-05` (F4 SCP eval engine) must land before `phase-08` (F7) starts; F7 reuses that engine. In parallel: `phase-14` (memory fabric) and `phase-16` (cost guardrails) — both are prerequisites for a real production posture.
4. **Week 4.** `phase-13` (integration and e2e), `phase-15` (dual-mode execution) once every specialist has a stable deterministic mirror, `phase-17` (self-healing) once observability from phase-12 is in place. Plus prompt-injection corpus expansion and eval harness tuning.

## Phase File Structure

Every phase file has these sections, in order:

1. **Objective** — one paragraph, what this phase delivers.
2. **Deliverables** — bullet list of concrete artifacts.
3. **Interface Contracts** — Pydantic models, OpenAPI schemas, IAM policies, environment variables.
4. **Implementation Steps** — numbered, executable steps with acceptance conditions each.
5. **Prompt Templates** — for phases that add a Bedrock Agent.
6. **IAM Policy** — least-privilege JSON for the Lambda execution role(s).
7. **Test Plan** — unit, contract, prompt-injection, moto integration, evals.
8. **Acceptance Criteria** — the boolean checklist that gates PR merge.
9. **Risks & Mitigations** — known-unknowns, degradation paths.

## Branches

Each phase has a matching feature branch. Names:

- `feat/agents-foundation` (phase-00)
- `feat/agents-supervisor` (phase-01)
- `feat/agents-passrole` (phase-02, F1)
- `feat/agents-org-context` (phase-03, F2)
- `feat/agents-data-events` (phase-04, F3)
- `feat/agents-scp-impact` (phase-05, F4)
- `feat/agents-session-terminator` (phase-06, F5)
- `feat/agents-shadow-guard` (phase-07, F6)
- `feat/agents-collision-resolver` (phase-08, F7)
- `feat/agents-slr-guardian` (phase-09, F8)
- `feat/agents-rag` (phase-10)
- `feat/agents-guardrails` (phase-11)
- `feat/agents-observability` (phase-12)
- `feat/agents-integration` (phase-13)
- `feat/agents-memory` (phase-14)
- `feat/agents-dual-mode` (phase-15)
- `feat/agents-cost-guardrails` (phase-16)
- `feat/agents-self-healing` (phase-17)

All branches base on `main`. All PRs require: passing tests, ruff clean, mypy strict clean, at least one principal-engineer review.
