# aws-infra/ — AWS CDK v2 (Python) Infrastructure

Every AWS resource that runs IAM Sentinel, defined declaratively in Python CDK v2. This module is the sole IaC surface — no Terraform, no Pulumi, no manual ClickOps.

Authoritative canon: `SYSTEM_STATE.md`, `docs/ARCHITECTURE.md`, `docs/AGENTIC_DESIGN.md`, `docs/DATA_CONTRACTS.md`.

Note: the earlier `aws-infra/` scaffolding targeted TypeScript CDK. That direction is retired. Python CDK aligns with the AWS team's brief (Lambda code in Python, single language for platform + infra).

---

## 1. Module Purpose and System Boundaries

**Purpose.** Declaratively provision every AWS resource: DynamoDB tables, S3 buckets (evidence, reports, KB source), KMS keys, Bedrock Agents + Knowledge Base + Guardrail, Lambda functions and layers, API Gateway (REST + WebSocket), EventBridge rules, SQS/SNS, Step Functions Express (approval + Session Terminator fan-out), Athena workgroup + Glue catalog, CloudFormation StackSet for cross-account roles, CloudWatch dashboards + alarms.

**In scope.**
- All CDK stacks composing the IAM Sentinel deployment.
- Lambda function definitions (code path pulled from `agents/`, `backend/`).
- IAM roles and permission boundaries (least-privilege per §Security in `docs/ARCHITECTURE.md`).
- Cross-account read-only role StackSet.
- Bedrock Agents CDK constructs (Sentinel Prime + 8 specialists + collaborator associations).
- Guardrail publication via CDK custom resource.

**Out of scope.**
- Application code (owned by `agents/`, `backend/`, `adapters/`).
- Frontend deployment (owned by `frontend/`).

**Boundaries.**
- Runtime language: Python 3.12.
- IaC language: Python CDK v2.
- Consumes: code artifacts from `agents/`, `backend/`, `adapters/`.
- Produces: deployed AWS resources + CloudFormation outputs that `backend/`, `frontend/`, and CI consume.

---

## 2. Directory Tree

```
aws-infra/
├── README.md                       this file
├── pyproject.toml                  uv-managed, Python 3.12
├── cdk.json                        CDK v2 config
├── app.py                          CDK entry
├── docs/
│   ├── README.md                   phase index
│   ├── phase-00-cdk-foundations.txt
│   ├── phase-01-security-stack.txt
│   ├── phase-02-foundation-stack.txt
│   ├── phase-03-athena-stack.txt
│   ├── phase-04-lambda-stack.txt
│   ├── phase-05-bedrock-stack.txt
│   ├── phase-06-event-stack.txt
│   ├── phase-07-api-stack.txt
│   └── phase-08-crossaccount-stack.txt
├── src/
│   └── iam_sentinel_infra/
│       ├── __init__.py
│       ├── config.py               stage configs, model IDs, table names
│       ├── stacks/
│       │   ├── security_stack.py
│       │   ├── foundation_stack.py
│       │   ├── athena_stack.py
│       │   ├── lambda_stack.py
│       │   ├── bedrock_stack.py
│       │   ├── event_stack.py
│       │   ├── api_stack.py
│       │   └── crossaccount_stack.py
│       └── constructs/
│           ├── signed_object_lock_bucket.py
│           ├── sentinel_lambda.py         (Powertools + arm64 + tracing defaults)
│           ├── sentinel_bedrock_agent.py  (agent + action group + alias)
│           ├── guardrail_custom_resource.py
│           └── sentinel_permission_boundary.py
├── policies/
│   ├── cross_account_role_trust.json
│   ├── cross_account_role_permissions.json
│   ├── f5_cross_account_permissions.json   (scoped to /aws-reserved/sso.amazonaws.com/)
│   ├── kms_evidence_key_policy.json
│   ├── kms_data_key_policy.json
│   └── sentinel_permission_boundary.json
├── functions/                      (Lambdas whose source lives here, not in agents/)
│   ├── router/                     phase-15 router entry
│   ├── watchdog/                   phase-17 watchdog
│   ├── repair/                     phase-17 repair Lambdas
│   ├── kb_ingest/                  phase-10 KB ingest trigger
│   ├── kb_corpus_fetch/            phase-10 doc scraper
│   ├── kb_manifest_generate/       phase-10 quote manifest
│   ├── memory_semantic_syncer/     phase-14 syncer
│   └── cost_report_weekly/         phase-16 weekly report
├── dashboards/
│   ├── prime_overview.json
│   ├── f1..f8.json                 per-specialist
│   ├── ops.json
│   └── cost.json
└── tests/
    ├── snapshot/                   cdk-nag + snapshot tests per stack
    └── integration/
```

---

## 3. Tech Stack

- Python 3.12.
- `aws-cdk-lib==2.163.0`, `constructs==10.4.0`.
- `cdk-nag==2.28.187` (AwsSolutions + HIPAASecurity checks enabled on synth).
- `pytest`, `pytest-cdk` for snapshot tests.

Forbidden: Terraform, Pulumi, Serverless Framework, TypeScript CDK, hand-authored CloudFormation.

---

## 4. Stack Composition + Deploy Order

```python
# app.py
app = cdk.App()
sec  = SecurityStack(app, "SentinelSecurity", env=env)
foun = FoundationStack(app, "SentinelFoundation", env=env, security=sec)
ath  = AthenaStack(app, "SentinelAthena", env=env, foundation=foun)
lam  = LambdaStack(app, "SentinelLambda", env=env, security=sec, foundation=foun, athena=ath)
bed  = BedrockStack(app, "SentinelBedrock", env=env, security=sec, foundation=foun, lambdas=lam)
evt  = EventStack(app, "SentinelEvent", env=env, lambdas=lam, foundation=foun)
api  = ApiStack(app, "SentinelApi", env=env, lambdas=lam, bedrock=bed, security=sec)
xacc = CrossAccountStack(app, "SentinelCrossAccount", env=env, security=sec)   # StackSet target
```

Deploy order strictly `Security → Foundation → Athena → Lambda → Bedrock → Event → Api → CrossAccount(StackSet)`.

---

## 5. Roadmap

| Phase | File                                       | Delivers                                                        |
|-------|--------------------------------------------|-----------------------------------------------------------------|
| 00    | `phase-00-cdk-foundations.txt`             | Python CDK bootstrap, config, constructs, cdk-nag wiring        |
| 01    | `phase-01-security-stack.txt`              | KMS CMKs, Guardrail, permission boundary, break-glass STS       |
| 02    | `phase-02-foundation-stack.txt`            | 13 DDB tables, S3 buckets, SQS FIFO, SNS topics                 |
| 03    | `phase-03-athena-stack.txt`                | Glue catalog + `cloudtrail_logs` table with partition projection|
| 04    | `phase-04-lambda-stack.txt`                | Every Sentinel Lambda + Powertools layer + boto3 layer          |
| 05    | `phase-05-bedrock-stack.txt`               | Prime + 8 specialists + KB + collaborator associations          |
| 06    | `phase-06-event-stack.txt`                 | EventBridge rules, scheduled expressions, CloudWatch alarms     |
| 07    | `phase-07-api-stack.txt`                   | API Gateway REST + WebSocket + Cognito authorizer               |
| 08    | `phase-08-crossaccount-stack.txt`          | CloudFormation StackSet: SentinelCrossAccountRole in every member |

---

## 6. Environments and Parameterization

Stages: `dev`, `staging`, `prod`. Each stage has:
- Independent AWS account (recommended).
- Its own SSM namespace `/sentinel/{stage}/*`.
- Its own Guardrail version.
- Its own KMS CMKs.
- Its own DDB tables suffixed by stage.

`env-{stage}.yaml` under `config/` carries: account id, region, allowed org root, model IDs, memory retention days, budget caps.

---

## 7. Non-Functional Requirements

- `cdk synth` clean on every stack.
- `cdk-nag` reports zero AwsSolutions violations at severity Error.
- Snapshot tests present per stack; changes require review.
- `cdk deploy --all` succeeds against a scratch AWS account within 30 minutes.
- Resources tagged `Project=IAMSentinel, Stage={stage}, Feature={feature_name}`.

---

## 8. Acceptance Criteria (Module-Wide)

- [ ] `uv run ruff check aws-infra/src` clean.
- [ ] `uv run mypy --strict aws-infra/src` clean.
- [ ] `cdk synth` succeeds for all stages.
- [ ] Snapshot suite green.
- [ ] `cdk-nag` clean at Error severity.
- [ ] End-to-end `cdk deploy --all` on scratch account passes smoke tests (POST /agent/chat returns a DecisionRecord in < 60 s).
