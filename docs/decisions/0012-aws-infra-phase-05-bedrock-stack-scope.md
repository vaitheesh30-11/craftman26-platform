# ADR 0012 — aws-infra phase-05: Bedrock stack scope — Knowledge Base + agent substrate, not Prime/the 8 specialists

Status: accepted
Date: 2026-07-30

## Context

`aws-infra/docs/phase-05-bedrock-stack.txt` §2 lists 8 deliverables. Two of
them — the Knowledge Base (§3) and the reusable agent-construct surface
(§4-§7's `SentinelBedrockAgent`/alias/collaborator shapes) — are buildable
today with no missing dependency. The other six all assume Sentinel Prime
and the 8 specialists already have real content to instantiate them with:// wait
their instruction prompts (`agents/src/iam_sentinel_agents/prompts/*.txt`)
and action-group OpenAPI specs (`agents/src/iam_sentinel_agents/action_groups/*.yaml`).
Neither directory exists yet — `agents/src/iam_sentinel_agents/` currently
has only `contracts/`, `knowledge_base/`, and `tools/` (from agents
phase-00 and agents phase-10). Sentinel Prime is built by agents phase-01
(sprint step 16, the very next step after this one); the 8 specialists are
split across Wave 3 (F1, sprint step 18) and Wave 6 (F2-F8, sprint steps
27-33).

This is the same shape of problem ADR 0011 (aws-infra phase-04)
already hit for the ~25 registry Lambdas, and ADR 0010 (agents phase-10)
flagged from the other direction: ADR 0010 explicitly listed "`SentinelKBStack`
itself... no `aws-infra` sprint step currently pairs with this one" as its
first deferred item — this phase is that pairing, and closes it.

Separately, `aws-cdk-lib==2.163.0`'s `CfnAgent` L1 (the version this repo
pins, per phase-05 §10's own risk mitigation: "pin `aws-cdk-lib` version")
has no `agentCollaboration` or `memoryConfiguration` property. Confirmed via
`boto3==1.35.36`'s service model that the real `CreateAgent`/`UpdateAgent`
APIs already support both fields — the CDK L1 simply predates the GA
multi-agent-collaboration surface, exactly the volatility phase-05 §10
warns about.

## Decision

- **Build the Knowledge Base (§3) in full**: `SentinelKB`
  (`aws_bedrock.CfnKnowledgeBase`), a dedicated `sentinel-kb-vector`
  OpenSearch Serverless collection (encrypted with `SecurityStack.kb_key`,
  provisioned exactly for this — see its docstring anticipating "aws-infra
  phase-05"), a vector-index bootstrap Lambda mirroring `oss_index_bootstrap`
  (aws-infra phase-02 / ADR 0005: hand-signed SigV4, not `opensearchpy`),
  the KB service role, and 4 `CfnDataSource`s (FIXED_SIZE 512-token/20%-
  overlap chunking) over `FoundationStack.kb_source_bucket` — a bucket
  aws-infra phase-02 already provisioned anticipating this exact consumer.
  Reused it rather than creating a colliding `SentinelKbSource-{stage}`
  bucket the spec's own pseudocode names (same shape of cross-stack
  collision ADR 0005/0009 already caught).
- **Build the reusable agent substrate**: `BedrockStack.new_agent()`
  (creates a least-privilege execution role scoped to InvokeModel on the
  caller's foundation model, ApplyGuardrail on the LIVE guardrail,
  Retrieve/RetrieveAndGenerate on `SentinelKB`; wires the guardrail and KB
  automatically; publishes `/sentinel/agents/{name}/alias/{alias}` SSM
  params) and `BedrockStack.associate_collaborator()` — the same
  "shared substrate now, owning phase calls it later" split ADR 0011
  established for `LambdaStack.new_function()`.
- **Do not instantiate Sentinel Prime or any of the 8 specialists.** Each
  lands with its owning phase (agents phase-01 for Prime; the Wave-3/6
  specialist phases for F1-F8), calling `new_agent()` with its own
  instruction text and action groups exactly the way F3/F4/F6's future
  Lambdas will call `LambdaStack.new_function()`.
- **Close the `agentCollaboration`/`memoryConfiguration` CDK-L1 gap** with
  `AgentSettingsCustomResource`, a Lambda-backed custom resource wrapping
  `UpdateAgent` (full-replace API — it re-requires `agentName`/
  `foundationModel`/`instruction`/`agentResourceRoleArn`, so
  `SentinelBedrockAgent` now requires an explicit `agent_resource_role_arn`
  whenever either field is set — CFN's auto-generated service role has no
  attribute exposing its own ARN back to the stack). `new_agent()` always
  supplies its own role, so this requirement is invisible to callers.
- **Implement collaborator associations (§6) via `AgentCollaboratorAssociation`**,
  a Lambda-backed custom resource wrapping `AssociateAgentCollaborator`/
  `UpdateAgentCollaborator`/`DisassociateAgentCollaborator` — CloudFormation
  has no native `AWS::Bedrock::AgentCollaborator` resource, the same gap
  `GuardrailCustomResource` (aws-infra phase-01) already closes for
  `AWS::Bedrock::Guardrail`. Always targets the Supervisor's `DRAFT`
  version, since a collaborator must be associated before `PrepareAgent`
  promotes a version.
- **Alias promotion workflow (§7) is out of scope entirely**: it is a
  GitHub Actions CD pipeline (prepare a version, run the eval harness,
  promote on pass), and this repo has no `.github/workflows` CD automation
  yet (same gap ADR 0011 already noted for the layer-build CodeBuild
  pipeline).
- **Real bug found and fixed in `SecurityStack`'s existing Guardrail
  lifecycle Lambda**: its `Update` branch never returned `GuardrailArn` in
  the custom resource's `Data` — only `Create` did. CloudFormation custom-
  resource attributes are replaced wholesale by each response, not merged,
  so any `Fn::GetAtt ...GuardrailArn` reference (which `new_agent()`'s
  `ApplyGuardrail` policy statement needs) would have silently broken the
  first time the Guardrail's policy content changed and `Update` ran.
  Fixed by calling `update_guardrail`'s own response for the ARN (it
  doesn't change on update, but must still be re-emitted).

## Consequences

Deferred — tracked in `docs/EXECUTION_STATE.txt`, not silently dropped —
because they need content from a phase that hasn't landed, a real AWS dev
account, or both:

1. "All 9 agents PREPARED without warnings" — none of the 9 exist yet.
   Each owning phase must call `new_agent()` and confirm `PrepareAgent`
   succeeds once it has real instruction/action-group content.
2. "KB ingestion succeeds on first deploy" — needs the actual AWS-doc
   corpus uploaded to `kb_source_bucket`'s 4 prefixes and a real
   `StartIngestionJob` call on a deployed KB; no scraper/uploader Lambda
   exists yet (ADR 0010 also deferred `kb_corpus_fetch`/`kb_ingest_trigger`
   for the same reason).
3. "Prime routes to correct specialist on 10 canonical prompts" and
   "Collaborator: multi-specialist prompt reaches >= 2 collaborators" —
   need Prime plus at least 2 specialists deployed and invokable.
4. "Alias promotion workflow executes end-to-end on staging" — needs the
   GH Actions CD pipeline this repo doesn't have yet.
5. Post-deploy sanity check (§10 risk mitigation: invoke each action-group
   Lambda directly with a synthetic Bedrock envelope) — no action-group
   Lambda exists yet to invoke.

Testing scope reduced per the revised policy: `AgentSettingsCustomResource`
and `AgentCollaboratorAssociation`'s handlers are unit-tested against a
mocked `boto3` client (same shape as `guardrail_lifecycle`'s existing
tests), not against a live `bedrock-agent` API. cdk synth + cdk-nag are the
only checks that run against the real toolchain for the KB/OSS resources —
there is no moto backend for either `bedrock-agent` or
`opensearchserverless`.
