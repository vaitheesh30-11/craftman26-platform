# SYSTEM_STATE.md — Sentinel-IQ v8

Universal AI project memory. Every AI coding tool (Codex, Claude, Cursor) that opens this repository MUST read this file first. Nothing in this repository is authoritative outside of what this file references.

## 1. Architectural Summary and System Boundaries

Sentinel-IQ v8 is an Autonomous Enterprise Governance Platform for continuous IAM, SCP, Permission Boundary, Trust Policy, Resource Policy, and Identity Center Permission Set drift detection, reasoning, and safe remediation across AWS Organizations.

Runtime shape: a deterministic rule engine classifies roughly 70 percent of drifts instantly (Rules R0-R6); the remaining 30 percent are handled by a five-agent Governance Council orchestrated through a Step Functions Express Workflow. Access Analyzer Zelkova (`CheckNoNewAccess`) provides mathematical safety proofs; Policy Simulator remains only for effective-permission checks.

System boundaries:
- AWS is the source of truth. No persistent posture mirror.
- Sentinel-IQ operates under an Organization SCP and permission boundary it cannot modify.
- Every artifact is KMS-signed and stored in S3 Object Lock.
- Every agent invocation passes through XML-fenced prompt sanitization and the published Bedrock Guardrail.

Full architecture in `docs/ARCHITECTURE.md`.

## 2. Key Engineering Rules

- **Zelkova mathematical proof**: every AutoRemediate is pre- and post-verified via `access-analyzer:CheckNoNewAccess`. If the API returns a violation with a witness counter-example, the action downgrades to Escalate. Never rely on `SimulatePrincipalPolicy` alone for the "does the candidate grant more than baseline" question.
- **15-second IAM eventual consistency backoff**: post-remediation verification runs inside a Step Functions Wait state of 15 seconds followed by Zelkova post-check, with a maximum of 3 polling iterations before rollback.
- **SCP 5000-byte safe threshold**: AWS Organizations rejects SCPs over 5,120 bytes. Rule R5 enforces a deterministic byte-size predicate at 5,000 bytes; any candidate SCP over that threshold downgrades from AutoRemediate to RequestApproval automatically.
- **XML prompt fencing**: tenant-controlled metadata (tags, runbook fragments, policy names, resource names) is sanitized and injected inside `<untrusted_context type="...">` XML fences. Structured input goes inside `<trusted_input>`. System prompts teach the model that untrusted content is data, never instructions.
- **Step Functions Express Workflows**: Council orchestration runs in Express (per-invocation billing, 5-minute ceiling). Standard workflows only for approval-callback paths that outlive 5 minutes.
- **In-memory ResultPath aggregation**: parallel agent outputs are captured via Step Functions `ResultPath`. No DynamoDB shared-memory writes. No race conditions by construction.
- **Bedrock model routing**: Haiku is default for all five agents. The Council orchestrator escalates to Sonnet only when specialist dissent rate exceeds 0.5.
- **Two-signer break-glass**: any modification to Sentinel-IQ's own SCP, permission boundary, or KMS key policy requires a session tagged `BreakGlass=SentinelIQ-Two-Signer` issued via CloudTrail-alarmed short-lived STS.
- **Conservative-default failure contract**: any agent failure (Bedrock timeout, Guardrail intervention, schema mismatch, output forgery) yields the agent's most conservative verdict; the Council default is Escalate.

## 3. Complete Directory Map

```
sentinel-iq/
├── SYSTEM_STATE.md               Universal AI project memory (this file)
├── README.md                     Repository entrypoint
├── docs/                         Central contracts, architecture, epics
│   ├── ARCHITECTURE.md           System design blueprint
│   ├── API_SPEC.md               REST + WebSocket contract
│   ├── DATA_CONTRACTS.md         DiffArtifact, SpecialistVerdict, DecisionRecord, IntentBaseline
│   ├── EPICS_AND_STORIES.md      GitHub-Issue-ready delivery matrix
│   └── README.md                 Docs navigation
├── frontend/                     Next.js 14 App Router governance dashboard
│   └── README.md                 Frontend implementation guide
├── backend/                      FastAPI + WebSocket management API
│   └── README.md                 Backend implementation guide
├── aws-infra/                    AWS CDK v2 (TypeScript) stacks
│   └── README.md                 Infra implementation guide
├── adapters/                     AWS API wrappers (Zelkova, Bedrock, Security Hub, KMS, S3)
│   └── README.md                 Adapters implementation guide
├── agents/                       Bedrock reasoning agents
│   ├── README.md                 Agents implementation guide (IIA, CSA, BRA, CAA, GC)
│   ├── iia/                      Intent Interpretation Agent
│   ├── csa/                      Context Synthesis Agent
│   ├── bra/                      Blast Radius Analyst
│   ├── caa/                      Compliance Advisor Agent
│   └── council/                  Governance Council Orchestrator
```

Every top-level directory in the map above is populated with either its module `README.md` or its authoritative doc set. Application code has not yet been generated; that work is driven by the epics in `docs/EPICS_AND_STORIES.md` and the per-module implementation guides.

## 4. Cross-Module Integration Matrix

| Producer | Consumer | Contract | Transport |
|---|---|---|---|
| Normalizer Lambda (aws-infra) | Decision Lambda (aws-infra) | DiffArtifact | SQS |
| Decision Lambda | Step Functions Express (aws-infra) | DiffArtifact + rule-branch metadata | Direct invocation |
| Step Functions Express | Specialist Agents (agents/{iia,csa,bra,caa}) | DiffArtifact + agent-specific context | Lambda invocation with ResultPath capture |
| Specialist Agents | Council Orchestrator (agents/council) | SpecialistVerdict | Step Functions state |
| Council Orchestrator | Executor Lambda (aws-infra) | DecisionRecord + optional RemediationPlan | Direct invocation |
| Executor Lambda | Zelkova client (adapters) | Policy pair | Boto3 `access-analyzer:CheckNoNewAccess` |
| Executor Lambda | S3 Object Lock (adapters) | ActionRecord | Signed PutObject |
| Executor Lambda | Security Hub (adapters) | DecisionRecord as ASFF | Boto3 `BatchImportFindings` |
| Backend API (backend) | Evidence lake + DynamoDB | Read-only queries | Boto3 |
| Backend API | Frontend (frontend) | REST + WebSocket per `docs/API_SPEC.md` | HTTPS + WSS |
| Frontend | Backend API | Approval decisions, baseline uploads | HTTPS |
| Approval Provider (Change Manager / ServiceNow) | Step Functions Standard | Callback token | HTTPS webhook |

## 5. Data Contract References

All four contracts are canonically defined in `docs/DATA_CONTRACTS.md`. Every producer and consumer MUST validate at both boundaries.

| Contract | Where used |
|---|---|
| `DiffArtifact` | Normalizer → Decision → Agents → Council → Executor → Evidence Lake |
| `SpecialistVerdict` | Agent → Council Orchestrator (aggregated via Step Functions ResultPath) |
| `DecisionRecord` | Council → Executor → Security Hub → Backend API → Frontend |
| `IntentBaseline` | Baseline signer → S3 Object Lock → Decision Lambda (verified on every read) |

## 6. Repository State

Populated: directory tree, `SYSTEM_STATE.md`, `docs/*.md`, `frontend/README.md`, `backend/README.md`, `aws-infra/README.md`, `adapters/README.md`, `agents/README.md`.

Not yet populated: any application code. Code generation follows the epics in `docs/EPICS_AND_STORIES.md`, driven by the per-module implementation guides.
