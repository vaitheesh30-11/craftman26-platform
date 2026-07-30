# IAM Sentinel — Architecture

## 0. Executive Summary

IAM Sentinel is an AWS-native agentic platform that closes eight gaps in AWS IAM and AWS Organizations SCP that AWS itself acknowledges in its official documentation. It uses Amazon Bedrock Agents multi-agent collaboration (a Supervisor agent named Sentinel Prime plus eight domain-specialist agents), Bedrock Guardrails on every invocation, Bedrock Knowledge Base grounded on the AWS Service Authorization Reference and IAM documentation, and Access Analyzer Zelkova (`CheckNoNewAccess`) as a mathematical safety proof before every policy write.

The winning story is not the tech stack — it is the product story: the platform surfaces classes of findings AWS's own tools cannot produce, and every finding cites the AWS document that proves the gap exists.

## 1. System Boundaries

| Boundary       | Value                                                                                   |
|----------------|------------------------------------------------------------------------------------------|
| Runtime        | Python 3.12 on AWS Lambda arm64; Bedrock Agents; Step Functions Express.                 |
| IaC            | AWS CDK v2 in Python (single app, multi-stack).                                          |
| Trust surface  | Central account (mgmt / delegated admin) + cross-account read-only role in each member. |
| Data plane     | DynamoDB single-table findings, S3 Object Lock evidence, Bedrock KB, RDS Aurora audit.   |
| Control plane  | API Gateway REST + Lambda authorizer, EventBridge triggers, SNS/SQS fan-out.             |
| Human plane    | Optional Next.js dashboard (see `frontend/`); CLI + REST are first-class.                |

Zero mutation outside Sentinel's own resources. Cross-account roles are read-only except for two narrowly scoped exceptions: (a) Feature 3 may call `cloudtrail:PutEventSelectors` to enable S3 data-event logging with explicit consent, and (b) Feature 5 may call `iam:PutRolePolicy` / `iam:DeleteRolePolicy` only against roles under the `/aws-reserved/sso.amazonaws.com/` path.

## 2. Layered View

```
                     ┌─────────────────────────────────────────┐
                     │  Human plane                            │
                     │  API Gateway REST · WebSocket · CLI     │
                     └─────────────────┬───────────────────────┘
                                       │ SentinelQuery
                     ┌─────────────────▼───────────────────────┐
                     │  Reasoning plane                        │
                     │  Sentinel Prime (Bedrock Supervisor)    │
                     │  + 8 Specialist Bedrock Agents          │
                     │  + Bedrock KB + Bedrock Guardrails      │
                     └─────────────────┬───────────────────────┘
                                       │ Tool invocations (OpenAPI action groups)
                     ┌─────────────────▼───────────────────────┐
                     │  Action plane                           │
                     │  Lambda tools per feature (F1..F8)      │
                     │  + Zelkova adapter (CheckNoNewAccess)   │
                     │  + Athena engine (CloudTrail queries)   │
                     └─────────────────┬───────────────────────┘
                                       │ boto3 (STS AssumeRole → member accounts)
                     ┌─────────────────▼───────────────────────┐
                     │  AWS surface                            │
                     │  IAM · Organizations · Access Analyzer  │
                     │  Identity Center · CloudTrail · S3      │
                     └─────────────────────────────────────────┘
```

## 3. Agent Topology

Sentinel Prime is a Bedrock Agent configured with the multi-agent collaboration Supervisor pattern. Its Collaborators are the 8 specialists. Prime alone speaks with the user; specialists never emit human-facing text — they emit structured `SpecialistVerdict` payloads that Prime synthesizes.

| Agent                     | ID | Model                                            | Owns                                   |
|---------------------------|----|--------------------------------------------------|----------------------------------------|
| Sentinel Prime            | –  | anthropic.claude-3-5-sonnet-20241022-v2:0        | Routing, plan, synthesis, narrative    |
| PassRole Cartographer     | F1 | anthropic.claude-3-5-haiku-20241022-v1:0         | Blast-radius graph over PassRole hops  |
| Org Context Validator     | F2 | anthropic.claude-3-5-haiku-20241022-v1:0         | False-positive suppression w/ org data |
| Data Event Enricher       | F3 | anthropic.claude-3-5-sonnet-20241022-v2:0        | Merge Athena S3 data events into policy|
| SCP Impact Analyst        | F4 | anthropic.claude-3-5-sonnet-20241022-v2:0        | Pre-deploy SCP change impact           |
| Session Terminator        | F5 | anthropic.claude-3-5-haiku-20241022-v1:0         | Emergency SSO/IAM session kill         |
| Shadow Guard              | F6 | anthropic.claude-3-5-haiku-20241022-v1:0         | Mgmt-account SCP shadow monitoring     |
| Collision Resolver        | F7 | anthropic.claude-3-5-sonnet-20241022-v2:0        | SCP inheritance intersection engine    |
| SLR Guardian              | F8 | anthropic.claude-3-5-haiku-20241022-v1:0         | Pre-deploy SLR breakage scan           |

Haiku is the default for reasoning-light specialists to keep cost and latency in check; Sonnet is reserved for specialists that must reason over long policy documents or merge structured artifacts. Model routing is centralized in `adapters/bedrock/model_router.py`.

## 4. Feature-to-Service Map

| Feature | Bedrock Agent          | Tool Lambdas (family)        | Primary AWS APIs                                                                                      | Data Sink                        |
|---------|------------------------|------------------------------|-------------------------------------------------------------------------------------------------------|----------------------------------|
| F1      | PassRole Cartographer  | passrole_scan, passrole_graph| `iam:List*`, `iam:Get*` across all member accounts via STS                                            | DDB `SentinelFindings` + SNS     |
| F2      | Org Context Validator  | org_context_scan, org_context_suppress | `accessanalyzer:ListFindings`, `accessanalyzer:CheckAccessNotGranted`, `organizations:ListAccounts` | DDB + Access Analyzer archive    |
| F3      | Data Event Enricher    | data_event_query, data_event_merge | `cloudtrail:GetEventSelectors`, `cloudtrail:PutEventSelectors`, `athena:StartQueryExecution`, `accessanalyzer:StartPolicyGeneration` | S3 policy versioned artifact     |
| F4      | SCP Impact Analyst     | scp_impact_simulate          | `organizations:ListParents`, `organizations:DescribePolicy`, `athena:StartQueryExecution`             | S3 report + DDB                  |
| F5      | Session Terminator     | session_kill_dispatch, session_kill_cleanup | `sso-admin:ListAccountAssignments`, `iam:PutRolePolicy` (aws-reserved path), `iam:DeleteRolePolicy` | DDB + SNS + Security Hub         |
| F6      | Shadow Guard           | shadow_guard_ingest, shadow_guard_report | CloudWatch Logs subscription, `organizations:ListPoliciesForTarget`                               | DDB + S3 weekly report           |
| F7      | Collision Resolver     | collision_resolve            | `organizations:ListParents`, `organizations:ListPoliciesForTarget`, `organizations:DescribePolicy`    | DDB + S3 effective-policy blob   |
| F8      | SLR Guardian           | slr_scan, slr_db_refresh     | `iam:ListPolicies` (AWS-scope), curated DDB                                                            | DDB `SentinelSLRs` + S3 report   |

## 5. AWS Service Topology

**Core storage.**
- `SentinelFindings` (DDB, on-demand, KMS CMK, PITR on). PK `account_id#feature_id`, SK `finding_id#timestamp`. GSI1 `severity#timestamp`, GSI2 `feature_id#status`. TTL `expires_at`.
- `SentinelPolicies` (DDB). Cached SCP + IAM policy documents; PK `org_id`, SK `policy_arn`. TTL 15 min.
- `SentinelSLRs` (DDB). Curated Service-Linked Role → required actions map; PK `service_principal`.
- `SentinelEvidence` (S3 Object Lock, compliance mode, KMS CMK, versioning). Content-addressed keys.
- `SentinelReports` (S3, KMS CMK, versioning, block public access). Weekly/on-demand narrative reports.
- `SentinelAudit` (RDS Aurora Serverless v2 PostgreSQL). Full audit trail for humans, PITR + snapshot exports.

**Compute.**
- 8 specialist agents × their tool Lambdas (Python 3.12, arm64, Powertools).
- Sentinel Prime executes inside Bedrock; no user Lambda.
- Session Terminator uses SQS FIFO fan-out (MessageGroupId per account) with per-account concurrency = 1.

**Eventing.**
- EventBridge triggers: GuardDuty findings (F5), Identity Center account-assignment events (F5), CloudTrail management-event delivery (F6), scheduled expressions for weekly reports.
- SNS topics: `SentinelCriticalFindings`, `SentinelEmergencyRevocations`, `SentinelWeeklyReports`.
- SQS: `SessionKillQueue` (FIFO), plus DLQs for every Lambda.

**Networking.**
- No VPC. All AWS control-plane calls; VPC only introduces cold-start latency and NAT cost. Lambdas talk to AWS regional endpoints over the AWS network.

**Identity.**
- Central account hosts the Bedrock Agents, all tool Lambdas, and DDB tables.
- StackSet deploys `SentinelCrossAccountRole` to every member account. Trust: only the central Lambda execution role can assume. Permissions: `iam:Get*`, `iam:List*`, `organizations:Describe*`, `organizations:List*`, `accessanalyzer:*` (List/Get/Update), `cloudtrail:Get*/List*/Put*` (F3-only, scoped by resource tag), `sso-admin:List*/Describe*`, plus the F5-specific `iam:PutRolePolicy` / `iam:DeleteRolePolicy` scoped by role path.

## 6. CDK Stack Composition

```
SentinelApp (cdk.App)
├── SentinelSecurityStack       KMS CMKs, permission boundary, Guardrail (CustomResource)
├── SentinelFoundationStack     DDB tables, S3 buckets, SQS, SNS
├── SentinelIAMStack            Lambda roles, Bedrock Agent execution roles
├── SentinelAthenaStack         Glue Data Catalog table, workgroup, S3 results bucket
├── SentinelLambdaStack         All Lambda functions + Powertools layer + boto3 layer
├── SentinelBedrockStack        Sentinel Prime + 8 Specialists + KB + action groups
├── SentinelEventStack          EventBridge rules, scheduled expressions, CW alarms
├── SentinelAPIStack            API Gateway REST + Lambda authorizer + WebSocket
└── SentinelCrossAccountStack   StackSet target: SentinelCrossAccountRole
```

Deploy order: `Security → Foundation → IAM → Athena → Lambda → Bedrock → Event → API → CrossAccount (StackSet)`.

## 7. Data Flow Per Feature (Sequences)

### F1 PassRole Cartographer
1. Human asks Prime: "audit passrole for account 111122223333".
2. Prime routes to F1 Specialist. Specialist calls `passrole_scan(account_id)`.
3. Lambda assumes `SentinelCrossAccountRole` in target account.
4. Lambda lists all users/roles/policies, parses statements, extracts `iam:PassRole` grants.
5. Lambda builds a NetworkX directed graph, calls `passrole_graph(edges)` to score blast radius.
6. `Finding` records written to DDB with citation to IAM User Guide PassRole note.
7. If any principal is `CRITICAL`, SNS `SentinelCriticalFindings` fires.
8. Prime synthesizes narrative and returns to human.

### F5 Session Terminator (Break-Glass)
1. Trigger: GuardDuty finding via EventBridge, or `POST /emergency/kill-session`, or Identity Center `DeleteAccountAssignment`.
2. Prime routes to F5 Specialist. Specialist calls `session_kill_dispatch(principal_arn, permission_set_arn, ttl_seconds, reason)`.
3. Discovery Lambda enumerates target accounts via `sso-admin:ListAccountAssignments`, resolves each account's `AWSReservedSSO_{name}_{random}` role ARN via `iam:ListRoles` with path `/aws-reserved/sso.amazonaws.com/`.
4. Fan out to SQS FIFO with MessageGroupId per account.
5. Per-account worker Lambda assumes cross-account role, `iam:PutRolePolicy` an inline Deny bound to `aws:TokenIssueTime < now()`.
6. TTL record persisted to DDB. EventBridge scheduled expression at TTL fires cleanup Lambda that `iam:DeleteRolePolicy`.
7. Every step KMS-signed and written to `SentinelEvidence`. Security Hub finding raised (ASFF).

Other features follow the same shape; details live in the per-feature phase docs.

## 8. Security Model

- **Guardrails.** One published Bedrock Guardrail with denied topics (jailbreaks, prompt injection), sensitive-info filter (mask ARNs from output unless explicitly requested), and contextual grounding (>=0.8 with the KB as source of truth).
- **XML prompt fencing.** All untrusted strings (role names, tag values, policy names) enter prompts inside `<untrusted_context type="...">` blocks with sanitizer applied (Unicode NFKC, strip control chars, cap length, reject forbidden patterns).
- **Zelkova pre/post-check.** Any specialist that writes IAM/SCP/permission-set MUST pass `CheckNoNewAccess` with the current policy as baseline. A 15-second wait + 3-poll post-check rejects eventual-consistency violations.
- **Two-signer break-glass.** Modifying Sentinel's own resources (SCP, permission boundary, KMS keys, Guardrail) requires a session tagged `BreakGlass=IAMSentinel-Two-Signer` from short-lived STS. CloudTrail alarms fire on every use.
- **Evidence.** Every specialist output canonicalized (RFC 8785 JCS), KMS-signed (`RSASSA_PSS_SHA_256`), written to Object Lock compliance-mode bucket. Signature verified on every read.
- **Least privilege.** No `*` in Action or Resource unless documented with an inline comment naming the API surface. IAM roles per specialist; no shared execution role.

## 9. Deployment Targets

- Central account: `SentinelSecurityStack`, `SentinelFoundationStack`, `SentinelIAMStack`, `SentinelAthenaStack`, `SentinelLambdaStack`, `SentinelBedrockStack`, `SentinelEventStack`, `SentinelAPIStack`.
- Delegated admin accounts:
  - Access Analyzer delegated admin: F2 (Org Context Validator) — read/update Access Analyzer findings.
  - Identity Center delegated admin: F5 (Session Terminator) — enumerate account assignments.
  - Organizations management: F4, F6, F7 — Org APIs are only callable from mgmt or a delegated admin.
- Member accounts: `SentinelCrossAccountStack` via CloudFormation StackSet targeting the entire org (excludes central account).

## 10. Cost Model (Sizing Guide)

- Bedrock Agent invocations dominated by F3 (Sonnet) and F4/F7 (Sonnet). Budget ~$0.02–$0.10 per invocation depending on tool round-trips.
- Lambda: arm64 Graviton, reserved concurrency 10/function, 1–3 GB memory. Cold-start budget < 800 ms.
- DDB: on-demand; expect < 1 GB/month.
- S3 Object Lock: retention 7 years, compliance mode; expect < 5 GB/year.
- Athena: partitioned CloudTrail table; queries scoped to 90 days; expect < 100 GB scanned/query.
- RDS Aurora Serverless v2: 0.5–4 ACU auto-scale; PITR 7 days.

## 11. Observability

- **Logs.** All Lambdas use `aws_lambda_powertools.Logger` with correlation IDs propagated from Bedrock Agent request IDs.
- **Metrics.** Powertools `Metrics` → CloudWatch EMF. Standard metrics per Lambda: `Invocations`, `Errors`, `Duration`, `ThrottleCount`, `ColdStarts`. Custom: `SentinelFindings{severity}`, `SentinelZelkovaViolations`, `SentinelGuardrailInterventions`.
- **Traces.** Powertools `Tracer` with X-Ray active tracing. Every cross-account STS AssumeRole is a subsegment.
- **Dashboards.** One CloudWatch dashboard per specialist + a Prime overview dashboard. Anomaly detection alarms on error rate and duration.
- **Evals.** LLM-as-judge eval harness (`agents/docs/phase-12-observability-evals.txt`) with golden inputs per specialist; runs nightly against `dev` and pre-release against `prod`.

## 12. Non-Functional Targets

- p95 end-to-end latency ≤ 20 s for read-only specialists (F1, F2, F6, F7, F8).
- p95 ≤ 90 s for enrichment specialists (F3, F4) due to Athena and generated-policy poll loops.
- Session Terminator (F5) end-to-end: ≤ 30 s from trigger to first Deny attached across all accounts (100-account org).
- Zero uncontrolled writes. All writes go through the Zelkova pre-check → apply → 15-s wait → Zelkova post-check → success-or-rollback state machine.
