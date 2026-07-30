# adapters/docs — Phase Roadmap

Six phases. All depend on `phase-00`; the other five can execute in parallel.

| Phase | File                                    | Delivers                                                     |
|-------|-----------------------------------------|--------------------------------------------------------------|
| 00    | `phase-00-adapters-foundations.txt`     | Package layout, settings, errors, retry, cost meter, tests   |
| 01    | `phase-01-bedrock-adapter.txt`          | Bedrock runtime + agent-runtime clients + Guardrail + router |
| 02    | `phase-02-zelkova-adapter.txt`          | `CheckNoNewAccess` pre/post-check + StartPolicyGeneration    |
| 03    | `phase-03-prompts-adapter.txt`          | XML fencer + sanitizer                                       |
| 04    | `phase-04-evidence-adapter.txt`         | KMS-signed S3 Object Lock evidence + ASFF mapping            |
| 05    | `phase-05-ddb-adapter.txt`              | Findings, decisions, memory, budget, breakers, in-flight     |

## Branches

- `feat/adapters-foundation`
- `feat/adapters-bedrock`
- `feat/adapters-zelkova`
- `feat/adapters-prompts`
- `feat/adapters-evidence`
- `feat/adapters-ddb`
