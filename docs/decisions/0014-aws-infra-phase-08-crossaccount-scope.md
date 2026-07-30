# ADR 0014 — aws-infra phase-08: cross-account StackSet scope, deferred criteria

Status: accepted
Date: 2026-07-31

## Context

`aws-infra/docs/phase-08-crossaccount-stack.txt` requires a `SERVICE_MANAGED`
CloudFormation StackSet with `AutoDeployment` targeting an AWS Organization's
member accounts. `SERVICE_MANAGED` StackSets require "trusted access" for
CloudFormation StackSets to already be enabled in AWS Organizations, and the
whole mechanism only does anything once member accounts, an org root/OU, and
delegated-admin accounts actually exist. None of that exists in this offline
sandbox — `config/dev.yaml`'s `org_id`/`org_root_id`/`delegated_admin_*`
fields are still the placeholders `aws-infra` phase-00 introduced.

This is the same shape of gap ADR 0009 (Athena, no org trail bucket) and
ADR 0011 (Lambda registry, no owning-phase consumers yet) already hit: the
spec's infrastructure is real and buildable synth-only, but its *acceptance*
is a live-AWS-Organization property, not a `cdk synth` property.

Separately, phase-08 §6 promises the delegated-admin role "a slightly wider
Access Analyzer / SSO surface (see phases-02 and -03 in agents/docs)" —
agents phase-02 (F1, sprint step 18) and phase-03 (org-context) haven't
landed yet, so the exact additional actions those Lambdas will need are not
yet specified anywhere.

## Decision

- **Both StackSets are built and synth-verified, not deployed.**
  `CrossAccountStack` declares `CrossAccountRoleStackSet`
  (`SentinelCrossAccountRole-{stage}`, `SERVICE_MANAGED`, `AutoDeployment`
  enabled, targeting `stage_config.org_root_id` with
  `AccountFilterType=DIFFERENCE` against `stage_config.account_id` to exclude
  Sentinel's own central account per §2/§4) and
  `DelegatedAdminAccountRoleStackSet` (`SentinelDelegatedAdminAccountRole-
  {stage}`, targeting the two `delegated_admin_*_account` config values
  directly per §6).
- **Role templates are hand-built CloudFormation JSON**, not CDK `Stack`s —
  StackSets take a template body string, and CDK has no L2 for "the template
  a StackSet deploys." `_role_template()` embeds phase-08 §3's trust policy
  and Read-Only Bundle verbatim (both role's `Sid`s match the spec exactly:
  `IamRead`, `OrgRead`, `AccessAnalyzerRead`, `AccessAnalyzerUpdate`,
  `CloudTrailReadWrite`, `SsoAdminReadOnly`, `F5ScopedPutDelete`).
- **Delegated-admin role's "wider surface" is scoped to identical to the
  default role for now.** Per the same reasoning as ADR 0011: writing the
  extra Access Analyzer/SSO actions now means guessing at an API surface that
  agents phase-02/phase-03's own specs (not yet written) are the actual
  source of truth for. `_build_delegated_admin_stack_set`'s docstring points
  future readers here.
- **`SentinelPermissionBoundary` (aws-infra phase-00/01) is widened**: its
  `AllowCrossAccountRoleAssumption` statement now lists both
  `SentinelCrossAccountRole` and `SentinelDelegatedAdminAccountRole` by ARN
  pattern. Without this fix, no Sentinel Lambda could ever assume the new
  delegated-admin role regardless of its own attached policy — a real gap
  this phase closes before any consumer hits it, the same shape of fix
  ADR 0007 made to SSM parameter publication.
- **Drift detection (§5) is real, runnable code**: `crossaccount_drift_
  detector`'s Lambda calls `DetectStackSetDrift`, polls
  `DescribeStackSetOperation` with a bounded loop (the Lambda's own 10-minute
  timeout is the backstop), then counts `DRIFTED` instances via
  `ListStackInstances` and emits `IAMSentinel/CrossAccount.
  SentinelCrossAccountDrift` per StackSet, alarmed through
  `SecurityStack.security_topic`. It cannot be exercised end-to-end without a
  real StackSet that has actually deployed instances to drift-check.
- **New-account health check (§9 risk mitigation)** is a Step Functions
  workflow (`Wait` 30 minutes, matching AutoDeployment's worst-case
  propagation time, then `sts:AssumeRole` + `iam:GetRole` against the new
  account, alerting to `security_topic` on any failure via `Catch`),
  triggered by the `CreateAccountResult` Organizations service event on the
  default event bus — the same EventBridge-management-events path ADR 0002
  already established, no new Trail.
- **Testing**: `moto` has no CloudFormation StackSet backend (the same gap
  ADR 0008 hit for Access Analyzer) — `test_crossaccount_stack.py` asserts
  against the synthesized `AWS::CloudFormation::StackSet` resource
  properties and the embedded template body's JSON directly, rather than
  attempting a live StackSet call. The two Lambda handlers are unit-tested
  against mocked `boto3` clients via `importlib.util.spec_from_file_location`
  (per ADR 0009's precedent for same-named `handler.py` files).

## Consequences

Deferred until a real AWS Organization exists with trusted access enabled
for CloudFormation StackSets, at least one non-central member account, and
the two delegated-admin accounts actually delegated (tracked in
`docs/EXECUTION_STATE.txt`, not silently dropped) — all three of phase-08
§8's acceptance criteria:

1. "StackSet deployed to every current member account" — no member accounts
   exist in this sandbox.
2. "Drift detection returns `IN_SYNC` on all instances" — no deployed
   instances exist to be `IN_SYNC` or `DRIFTED`.
3. "Feature-tag conditions enforced (unit test: F1 tag cannot perform F5
   actions)" — verified here only as a static assertion that the `Condition`
   blocks exist with the right `Sid`s/tag keys in the template body; a real
   `iam:SimulatePrincipalPolicy` or live `sts:AssumeRole` call with a session
   tag is needed to prove enforcement, and no specialist Lambda that sets
   `aws:PrincipalTag/Feature` exists until agents phase-02 (F1, sprint step
   18) lands.

Also open: the delegated-admin role's actual wider Access Analyzer/SSO
surface, to be filled in once agents phase-02 and phase-03 specify it (see
Decision above) — reconcile then rather than guessing now.
