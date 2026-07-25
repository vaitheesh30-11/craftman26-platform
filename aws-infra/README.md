# aws-infra/ — AWS CDK v2 Infrastructure

AWS CDK v2 in TypeScript defining every managed resource for Sentinel-IQ v8: ingestion, decision engine, Step Functions Express + Standard workflows, evidence lake, KMS keys, IAM permission boundaries, Organization SCP, Bedrock Guardrail, DynamoDB tables, and API Gateway (WebSocket + REST).

---

## 1. Module Purpose and System Boundaries

**Purpose**. Every AWS resource that runs Sentinel-IQ, defined declaratively. Nothing else in the repo provisions AWS state.

**In scope**:
- CDK stacks for events, core, workflows, evidence, security, agents-runtime, api.
- Organization SCP, Sentinel-IQ Executor permission boundary, KMS key policies.
- Bedrock Guardrail publication as a CDK custom resource.
- EventBridge rules, SQS queues, Step Functions state machines (Express + Standard), Lambda function definitions (code deployed from `agents/`, `backend/`, and local Normalizer/Decision/Executor sources).
- S3 Object Lock buckets (compliance + governance mode).
- DynamoDB tables (rule set, connection registry, approval registry, in-flight decision state).
- API Gateway HTTP + WebSocket APIs backed by `backend/`.

**Out of scope**:
- Application code (delivered from `agents/`, `backend/`, `adapters/`, and the Normalizer/Decision/Executor Lambdas which live in a `functions/` subfolder inside this module).

**Boundaries**:
- CDK synthesizes and deploys.
- Never imports `frontend/` (Frontend deploys via Vercel/Amplify from `frontend/`).
- Uses `docs/DATA_CONTRACTS.md` only to reason about payload shapes for infra choices.

---

## 2. Files and Directory Tree to Generate

```
aws-infra/
├── package.json
├── tsconfig.json
├── cdk.json
├── README.md                          (this file)
├── bin/
│   └── sentinel-iq.ts                 CDK app entry
├── lib/
│   ├── events-stack.ts                EventBridge + SQS + Normalizer Lambda
│   ├── core-stack.ts                  Decision Lambda + Executor Lambda + rule DynamoDB
│   ├── workflows-stack.ts             Step Functions Express (Council) + Standard (Approval)
│   ├── evidence-stack.ts              S3 Object Lock buckets, Bedrock Knowledge Base
│   ├── security-stack.ts              Organization SCP, permission boundary, KMS keys, Bedrock Guardrail
│   ├── agents-runtime-stack.ts        Lambda definitions for IIA/CSA/BRA/CAA/Council (code from agents/)
│   ├── api-stack.ts                   API Gateway HTTP + WebSocket, Cognito user pool, Lambda targets
│   ├── constants.ts                   Sizing, timeouts, retention, IAM prefixes
│   └── constructs/
│       ├── signed-object-lock-bucket.ts
│       ├── zelkova-wrapper-lambda.ts
│       ├── guardrail-custom-resource.ts
│       └── sentinel-iq-permission-boundary.ts
├── functions/
│   ├── normalizer/                    (Code lives here; Story 2.3 fills this in.)
│   ├── decision/
│   ├── executor/
│   ├── backfill/
│   └── divergence/
├── policies/
│   ├── organization-scp.json          Text of the pinning SCP; deployed via CDK
│   ├── executor-permission-boundary.json
│   ├── kms-baseline-signer-key-policy.json
│   └── kms-plan-signer-key-policy.json
└── test/
    ├── snapshot/
    │   ├── events-stack.test.ts
    │   ├── core-stack.test.ts
    │   ├── workflows-stack.test.ts
    │   ├── evidence-stack.test.ts
    │   ├── security-stack.test.ts
    │   ├── agents-runtime-stack.test.ts
    │   └── api-stack.test.ts
    └── integration/
        ├── zelkova-post-check.test.ts
        └── express-workflow.test.ts
```

---

## 3. Tech Stack and Recommended Libraries

- AWS CDK v2 (aws-cdk-lib 2.150+).
- TypeScript 5.5+.
- `@aws-cdk/aws-stepfunctions-tasks` and `@aws-cdk/aws-stepfunctions` (Parallel + ResultPath).
- `@aws-cdk/aws-apigatewayv2-alpha` for WebSocket API.
- `aws-cdk-lib/aws-organizations` for SCP (or L1 with `AwsCustomResource` if a target OU is not managed by CDK).
- Jest for snapshot tests.
- `cdk-nag` (AwsSolutionsChecks + HIPAASecurityChecks) enabled on synth.

Do NOT introduce: Terraform, Pulumi, Serverless Framework, or any parallel IaC tool. CDK is the sole IaC surface.

---

## 4. Step-by-Step Implementation Instructions

### 4.1 Stack composition
1. `bin/sentinel-iq.ts` instantiates: `SecurityStack` → `EvidenceStack` → `EventsStack` → `CoreStack` → `AgentsRuntimeStack` → `WorkflowsStack` → `ApiStack`.
2. `SecurityStack` MUST synthesize before `CoreStack` because the permission boundary is a dependency of every executor role.

### 4.2 Ingestion (EventsStack)
1. EventBridge rule matching the published action list (documented in this file's section 6).
2. SQS main queue (visibility timeout 60 s) + DLQ (14-day retention).
3. Normalizer Lambda (Python 3.11, 512 MB, 30 s timeout) reading from SQS.
4. S3 evidence writer via KMS-signed PutObject.

### 4.3 Deterministic engine (CoreStack)
1. Decision Lambda (Python 3.11, 1024 MB, 30 s timeout).
2. Rule table DynamoDB (on-demand, PK `versionId`, SK `orderIndex`).
3. In-flight state DynamoDB (on-demand, TTL 24 h).
4. Zelkova wrapper Lambda in `constructs/zelkova-wrapper-lambda.ts`.

### 4.4 Council orchestration (WorkflowsStack)
1. Step Functions Express Workflow ASL: Parallel state (4 branches for IIA, CSA, BRA, CAA) → ResultPath `$.specialists` → Council invocation → decision branch.
2. Step Functions Standard Workflow for approval callback token pattern (Change Manager / ServiceNow).
3. Wait state (15 s) + Zelkova post-check + retry counter (max 3).

### 4.5 Agents runtime (AgentsRuntimeStack)
1. One Lambda function per agent (`iia`, `csa`, `bra`, `caa`, `council`), code from `agents/`.
2. Environment variables: `SENTINEL_IQ_GUARDRAIL_ID`, `SENTINEL_IQ_GUARDRAIL_VERSION`, model IDs.
3. IAM role: least privilege to call `bedrock:Converse`, `access-analyzer:CheckNoNewAccess` (BRA), Bedrock KB Retrieve (CAA).

### 4.6 Evidence (EvidenceStack)
1. `SignedObjectLockBucket` construct: Object Lock compliance mode for evidence; governance mode for explanations. Versioning ON. Default KMS.
2. Bedrock Knowledge Base for compliance controls + runbook fragments (data source = evidence-KB bucket).

### 4.7 Security (SecurityStack)
1. Organization SCP deployed via CDK L1 (`CfnOrganizationPolicy`) or `AwsCustomResource` targeting the Security OU.
2. Executor permission boundary policy from `policies/executor-permission-boundary.json`.
3. Two KMS keys with published key policies (baseline signer, plan signer).
4. Bedrock Guardrail custom resource publishing the configuration from `docs/ARCHITECTURE.md` section 5.

### 4.8 API (ApiStack)
1. API Gateway HTTP API → backend Lambda (from `backend/`).
2. API Gateway WebSocket API → four Lambda targets (`$connect`, `$default`, `$disconnect`, fanout).
3. Cognito user pool + hosted UI + JWT authorizer.

---

## 5. Exact Codex Prompts

**Prompt A — Bootstrap**
> Read `docs/ARCHITECTURE.md` and `docs/EPICS_AND_STORIES.md` Epic 2. Generate `aws-infra/bin/sentinel-iq.ts`, `aws-infra/lib/constants.ts`, and the seven stack files as skeletons that compose in the order specified in `aws-infra/README.md` section 4.1. `cdk synth` MUST succeed with empty resources.

**Prompt B — EventsStack**
> Fill in `aws-infra/lib/events-stack.ts`. Deploy the EventBridge rule matching the action list in `aws-infra/README.md` section 6, SQS main + DLQ + alarms, and the Normalizer Lambda (`functions/normalizer` code path). Include snapshot test.

**Prompt C — Express Workflow ASL**
> Fill in `aws-infra/lib/workflows-stack.ts`. Build the Step Functions Express state machine per `docs/ARCHITECTURE.md` section 6: Parallel with four branches (IIA/CSA/BRA/CAA) aggregating via ResultPath `$.specialists`, then Council invocation, then decision branch (AutoRemediate → Zelkova pre-check → Executor → Wait 15 s → Zelkova post-check with 3-iteration retry → Rollback on failure). Include integration test using AWS SAM local or moto.

**Prompt D — SecurityStack**
> Fill in `aws-infra/lib/security-stack.ts`. Deploy the Organization SCP from `aws-infra/policies/organization-scp.json`, the Executor permission boundary, two KMS keys with policies from `aws-infra/policies/*key-policy.json`, and the Bedrock Guardrail via `constructs/guardrail-custom-resource.ts`. Include snapshot test and a `cdk-nag` verification pass.

**Prompt E — EvidenceStack**
> Fill in `aws-infra/lib/evidence-stack.ts`. Provision two S3 buckets (compliance + governance Object Lock), Bedrock Knowledge Base with the evidence-KB bucket as its data source, and the required IAM roles for KB ingest.

**Prompt F — AgentsRuntimeStack + ApiStack**
> Fill in `aws-infra/lib/agents-runtime-stack.ts` (one Lambda per agent with code from `agents/`) and `aws-infra/lib/api-stack.ts` (API Gateway HTTP + WebSocket → `backend/`). Include Cognito user pool.

---

## 6. Event Sources — EventBridge Rule Pattern

The Normalizer must observe write-type actions across all six drift surfaces. Include, at minimum:

- IAM: `PutRolePolicy`, `DeleteRolePolicy`, `AttachRolePolicy`, `DetachRolePolicy`, `PutUserPolicy`, `PutGroupPolicy`, `CreatePolicyVersion`, `SetDefaultPolicyVersion`, `UpdateAssumeRolePolicy`, `PutRolePermissionsBoundary`, `DeleteRolePermissionsBoundary`.
- Organizations: `AttachPolicy`, `DetachPolicy`, `UpdatePolicy`, `CreatePolicy`, `DeletePolicy`.
- Identity Center: `PutInlinePolicyToPermissionSet`, `DeleteInlinePolicyFromPermissionSet`, `AttachManagedPolicyToPermissionSet`, `DetachManagedPolicyFromPermissionSet`, `ProvisionPermissionSet`, `CreateAccountAssignment`, `DeleteAccountAssignment`.
- STS: `AssumeRoleWithSAML`, `AssumeRoleWithWebIdentity` (for anomaly context, not decisions).
- Resource policies: `s3:PutBucketPolicy`, `s3:DeleteBucketPolicy`, `kms:PutKeyPolicy`, `sns:SetTopicAttributes`, `sqs:SetQueueAttributes`, `lambda:AddPermission`, `lambda:RemovePermission`, `secretsmanager:PutResourcePolicy`, `secretsmanager:DeleteResourcePolicy`, `ecr:SetRepositoryPolicy`, `ecr:DeleteRepositoryPolicy`.

The full canonical list is authoritative in `aws-infra/lib/constants.ts` once implemented.

---

## 7. Inputs, Outputs, and Integration Boundaries

**Inputs**:
- Deployment credentials (CI role from a GitHub OIDC provider).
- Code artifacts from `agents/`, `backend/`, and the Normalizer/Decision/Executor sources under `functions/`.

**Outputs**:
- Deployed AWS resources.
- CloudFormation stack outputs consumed by:
  - `frontend/` env: `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_WS_URL`, `NEXT_PUBLIC_COGNITO_POOL_ID`.
  - `backend/` env: `EVIDENCE_BUCKET`, `RULE_TABLE`, `WORKFLOW_ARN`, `GUARDRAIL_ID`, `KMS_BASELINE_KEY_ID`.

**Integration**:
- Never mutate AWS state outside of CDK. All ClickOps is prohibited.

---

## 8. Acceptance Criteria and Validation Commands

- `pnpm --filter aws-infra typecheck` clean.
- `pnpm --filter aws-infra test` snapshot suite passes.
- `pnpm --filter aws-infra cdk synth` produces valid templates for all seven stacks.
- `pnpm --filter aws-infra cdk deploy --all` succeeds against a scratch AWS account.
- `cdk-nag` reports zero AwsSolutions violations at severity Error.
- Deployed Step Functions Express state machine executes the three end-to-end scenarios from Epic 7.8 with p95 < 45 s.
