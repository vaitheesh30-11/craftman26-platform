# SYSTEM_STATE.md — IAM Sentinel

Universal project memory. Every AI coding tool (Claude, Codex, Cursor, Kilo) that opens this repository MUST read this file first. Nothing outside of what this file references is authoritative.

## 1. Platform Identity

**Name.** IAM Sentinel.
**Mission.** Close eight confirmed gaps in AWS IAM and AWS Organizations SCP that AWS itself acknowledges in its official documentation and cannot be solved by combining existing AWS services.
**Positioning.** AWS-native agentic platform: Amazon Bedrock Agents multi-agent collaboration, Bedrock Guardrails on every invocation, Bedrock Knowledge Base for grounded reasoning, Access Analyzer Zelkova (`CheckNoNewAccess`) for mathematical safety proofs before any policy write.
**Deployment surface.** Single AWS Organization. Central account (delegated administrator for Access Analyzer + Identity Center + Organizations) plus cross-account read-only roles in every member account. Zero mutation outside Sentinel's own StackSet.

The eight gaps and the specialist agents that close them are catalogued in `docs/AWS_GAPS.md`. Every design decision in this repository traces back to that catalogue.

## 2. Non-Negotiable Engineering Rules

1. **Documentation-first.** Every finding emitted by any agent MUST include the AWS documentation quote that proves the gap it addresses. Findings without provenance are rejected at contract time.
2. **Bedrock-native orchestration.** Multi-agent collaboration uses Bedrock Agents Supervisor + Collaborator pattern (GA December 2024). No LangGraph, no LangChain, no LlamaIndex, no LiteLLM. Direct `bedrock-agent-runtime:InvokeAgent` is authoritative.
3. **Zelkova pre- and post-check on every policy write.** Any specialist that produces an IAM/SCP/permission-set change MUST pass `access-analyzer:CheckNoNewAccess` before the change is applied and again after (with a 15-second IAM eventual-consistency wait, max 3 poll iterations). A witness counter-example downgrades the action to Escalate.
4. **XML prompt fencing.** Tenant-controlled or AWS-tenant-controlled data (tag values, role names, policy names, principal ARNs) is sanitized and injected inside `<untrusted_context type="...">` blocks. Structured tool input goes inside `<trusted_input>`. System prompts teach every model that untrusted content is data, never instructions.
5. **Guardrails on every invocation.** `bedrock:InvokeAgent` calls pass the published Guardrail ID. `stopReason == "guardrail_intervened"` is a terminal failure that surfaces as `GuardrailInterventionError`.
6. **Conservative-default failure.** Any agent failure (Bedrock timeout, Guardrail intervention, schema mismatch, forged-output detection, boto3 throttling exhaustion) yields the agent's most conservative verdict; the Supervisor default is Escalate to human, never AutoRemediate.
7. **SCP 5,000-byte safe threshold.** AWS Organizations rejects SCPs over 5,120 bytes. Any candidate SCP over 5,000 bytes downgrades from AutoRemediate to RequestApproval.
8. **Deterministic-first hybrid.** A deterministic rule engine handles ~70% of decisions (byte-size, format, block-list, static parse). The 8 specialist agents own the ~30% that require reasoning, RAG, or graph analysis.
9. **KMS-signed evidence, S3 Object Lock.** Every specialist output, every Zelkova invocation, every remediation action is canonicalized, KMS-signed, written to an Object Lock bucket. Signature verified on every read.
10. **Two-signer break-glass.** Modifying Sentinel's own SCP, permission boundary, KMS key policies, or Guardrail requires a session tagged `BreakGlass=IAMSentinel-Two-Signer` issued via CloudTrail-alarmed short-lived STS.
11. **Least privilege by default.** No `*` in `Action` or `Resource` unless documented in an inline comment referencing the specific AWS API surface it covers.

## 3. Repository Layout (Authoritative)

```
craftman26-platform/
├── SYSTEM_STATE.md               This file — read first, always.
├── README.md                     Repo entrypoint (points here).
├── docs/                         Platform-level architecture and contracts.
│   ├── ARCHITECTURE.md           System design blueprint.
│   ├── AGENTIC_DESIGN.md         Multi-agent collab, context/loop/RAG engineering.
│   ├── AWS_GAPS.md               The 8 AWS gaps with verbatim citations.
│   └── DATA_CONTRACTS.md         Pydantic v2 schemas for every producer/consumer.
├── agents/                       Bedrock Agent definitions + Lambda tool code.
│   ├── README.md                 Module contract.
│   └── docs/                     Phase-scoped delivery specs (phase-00 .. phase-13).
├── adapters/                     AWS API wrappers (Bedrock, Zelkova, KMS, S3, DDB).
├── aws-infra/                    AWS CDK v2 (Python) — all managed resources.
├── backend/                      FastAPI + API Gateway management API.
└── frontend/                     Next.js 14 governance dashboard.
```

All module contracts are IAM Sentinel canon: `agents/`, `adapters/`, `aws-infra/`, `backend/`, `frontend/`. See §7 for the per-module status snapshot.

## 4. Agent Topology (Read First Before Touching agents/)

**Supervisor.** `Sentinel Prime` — Amazon Bedrock Agent using the multi-agent collaboration Supervisor pattern. Model: `anthropic.claude-3-5-sonnet-20241022-v2:0`. Owns query routing, plan decomposition, cross-specialist synthesis, and human-facing narrative.

**Specialists (one per AWS gap).** Each is a Bedrock Agent with a curated action group (tool schema + Lambda), a Knowledge Base attachment, a Guardrail attachment, and a memory configuration.

| ID  | Specialist                | Closes AWS Gap                             | Lambda Family        |
|-----|---------------------------|--------------------------------------------|----------------------|
| F1  | PassRole Cartographer     | PassRole audit blind spot                  | `passrole_*`         |
| F2  | Org Context Validator     | Access Analyzer org-context ignorance      | `org_context_*`      |
| F3  | Data Event Enricher       | S3 data events missing from generated pols | `data_event_*`       |
| F4  | SCP Impact Analyst        | SCP change pre-deployment impact           | `scp_impact_*`       |
| F5  | Session Terminator        | SSO session vs IAM role session mismatch   | `session_kill_*`     |
| F6  | Shadow Guard              | Management account SCP shadow              | `shadow_guard_*`     |
| F7  | Collision Resolver        | SCP inheritance collision                  | `collision_*`        |
| F8  | SLR Guardian              | SLR breakage by proposed SCPs              | `slr_guardian_*`     |

Full agent scaffolding, prompts, tool schemas, IAM policies, and test plans live in `agents/docs/phase-01 .. phase-09.txt`.

## 5. Cross-Module Integration Matrix

| Producer                          | Consumer                          | Contract                | Transport                           |
|-----------------------------------|-----------------------------------|-------------------------|-------------------------------------|
| API Gateway / EventBridge         | Sentinel Prime Supervisor         | `SentinelQuery`         | `bedrock-agent-runtime:InvokeAgent` |
| Sentinel Prime                    | Specialist Bedrock Agent          | `SpecialistTask`        | Multi-agent collaboration hop       |
| Specialist Agent                  | Tool Lambda                       | OpenAPI action group    | Bedrock action-group invocation     |
| Tool Lambda                       | Findings table (DDB)              | `Finding`               | DDB PutItem with GSI                |
| Tool Lambda                       | Evidence bucket (S3 Object Lock)  | `EvidenceRecord`        | KMS-signed PutObject                |
| Tool Lambda (policy-mutating)     | Zelkova adapter                   | `PolicyPair`            | `access-analyzer:CheckNoNewAccess`  |
| Any agent output                  | Security Hub                      | ASFF Finding            | `securityhub:BatchImportFindings`   |
| Backend API                       | Frontend                          | REST + WebSocket        | HTTPS + WSS                         |

## 6. Contract References

All contracts are canonically defined in `docs/DATA_CONTRACTS.md`. Every producer and every consumer MUST validate at both boundaries. Contract summary:

- `SentinelQuery` — natural-language + optional structured filters from API Gateway.
- `SpecialistTask` — Supervisor → Specialist handoff with target ARN, feature ID, and untrusted-context blocks.
- `Finding` — universal schema for anything a specialist surfaces; carries `aws_doc_citation` field (mandatory).
- `EvidenceRecord` — KMS-signed, canonicalized JSON blob written to Object Lock.
- `DecisionRecord` — Supervisor-authored synthesis with links to all specialist verdicts and Zelkova proofs.

## 7. Repository State (2026-07-30)

All modules populated with IAM Sentinel canon:

| Module     | README      | Phase docs                                    |
|------------|-------------|-----------------------------------------------|
| repo root  | `SYSTEM_STATE.md`, `docs/ARCHITECTURE.md`, `docs/AGENTIC_DESIGN.md`, `docs/AWS_GAPS.md`, `docs/DATA_CONTRACTS.md` | – |
| `agents/`  | `agents/README.md` + `agents/docs/README.md` | `phase-00 .. phase-17.txt` (18 phases)        |
| `adapters/`| `adapters/README.md` + `adapters/docs/README.md` | `phase-00 .. phase-05.txt` (6 phases)   |
| `aws-infra/`| `aws-infra/README.md` + `aws-infra/docs/README.md` | `phase-00 .. phase-08.txt` (9 phases) |
| `backend/` | `backend/README.md` + `backend/docs/README.md` | `phase-00 .. phase-04.txt` (5 phases)   |
| `frontend/`| `frontend/README.md` + `frontend/docs/README.md` | `phase-00 .. phase-04.txt` (5 phases) |

Retired (do not trust): the LangGraph-flavored open-model output under `agents/docs/phase-1.txt` through `phase 7.txt` (deleted), the earlier `backend/docs/phase-*.txt` (deleted), the earlier `frontend/docs/phase-*.txt` (deleted), and the earlier framing of Sentinel-IQ v8 with a 5-agent Governance Council. The Zelkova + Guardrail + XML fencing + KMS-signed evidence primitives from that work are preserved and integrated; the 5-agent framing is replaced by the 8-specialist topology in Section 4.

Total phase files: 43 across all modules.
