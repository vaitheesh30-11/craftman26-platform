# ADR 0011 — aws-infra phase-04: Lambda stack scope — shared substrate only, not the ~25 registry functions

Status: accepted
Date: 2026-07-30

## Context

`aws-infra/docs/phase-04-lambda-stack.txt` §4 lists ~25 Lambda functions
grouped by family (`passrole_*`, `org_context_*`, `data_event_*`,
`scp_impact_*`, `session_kill_*`, `shadow_guard_*`, `collision_resolve`,
`slr_*`, `prime_post_turn`, `router`, `watchdog`/`repair_*`, `kb_*`,
`memory_*`, `cost_report_weekly`, `athena_curate_writes`, `drift_detector`).
The table's own "Owned by phase" column attributes every single one of
them to a specific future phase — agents phase-01 through phase-17 — none
of which have landed yet (this is sprint step 14 of 43; the first
specialist, agents phase-02/F1, is sprint step 18). `athena_curate_writes`
is the one exception already built, and it was built directly inside
`AthenaStack` (aws-infra phase-03), not through `LambdaStack`.

This is the same shape of problem ADR 0006 (adapters phase-05) and
ADR 0009 (aws-infra phase-03) already hit: a phase document assumes
consumers exist that this sprint's ordering hasn't reached yet. Writing
25 function *bodies* now means guessing at handler logic, IAM API
surfaces, and event shapes that each owning phase's own doc (e.g.
`agents/docs/phase-02-passrole-cartographer.txt`) is the actual source of
truth for — exactly the premature design this project's conventions
already reject.

Separately, phase-04 §3 specifies `PythonFunction` (from
`aws_cdk.aws_lambda_python_alpha`) "if available." That package is not a
dependency of this repo and pulls in Docker-based dependency bundling at
`cdk synth` time, which this offline sandbox cannot run. Every existing
Lambda in this repo (`athena_bootstrap`, `athena_curate_writes`,
`break_glass`, `guardrail_lifecycle`) already uses the documented fallback
— `aws_cdk.aws_lambda.Function` + `Code.from_asset` — establishing that as
this project's actual convention, not the alpha module.

Phase-04 §6 also specifies the Powertools and boto3 Lambda layers are
"built via CodeBuild at CI time" / "rebuilt monthly." No CodeBuild project
or CI pipeline exists yet in this repo to do that build.

## Decision

- **Scope this phase to the shared substrate only**: the two versioned
  layers (`SentinelPowertoolsLayer`, `SentinelBoto3Layer`, exported by ARN
  via SSM per §6 — the runtime Lambdas that will consume them "pin the
  version by ARN at deploy time" exactly as specified), and an enhanced
  `SentinelLambda` L3 construct + `LambdaStack.new_function()` /
  `LambdaStack.standard_environment()` factory that every owning phase
  calls when it lands. `SentinelLambda` now creates its own dedicated
  execution role (no role reuse, per §5), applies
  `SentinelPermissionBoundary`, and attaches the two standard alarms
  (`Errors > 5/5min`, an anomaly-detection band on `Duration`, per §2/§6).
  Reserved concurrency, memory (1024 MB default), and timeout (300s
  default) defaults now match this phase's §3 table; callers override per
  function (e.g. 3008 MB / 900s for pollers, 30s for real-time ingest) the
  same way `AthenaStack.grant_query_access()` (phase-03) is a public
  method other stacks call, not something phase-03 itself calls.
  `LambdaStack.new_function()` is that same pattern for this stack: it
  optionally calls `AthenaStack.grant_query_access()` itself
  (`needs_athena_query`/`needs_athena_write`) so F3/F4/F6's future roles
  get Athena access wired in one call once those phases land — this *is*
  the first phase that plumbs that call, even though no concrete caller
  exists yet to invoke it with `needs_athena_query=True`.
- **None of the ~25 registry functions are instantiated in this phase.**
  Each owning phase (agents phase-01 through -17) calls
  `LambdaStack.new_function()` from its own stack/construct when it
  lands, passing its own handler code, IAM statements, and any
  phase-specific memory/timeout override — the same division of
  responsibility already established between `AthenaStack` (owns its
  Glue/workgroup resources) and `LambdaStack` (owns the shared IAM/DLQ/
  alarm/layer plumbing every Lambda needs).
- **No `aws_lambda_python_alpha`, no CodeBuild pipeline**: layers are
  declared as versioned `LayerVersion` resources backed by placeholder
  asset directories (`functions/layers/{powertools,boto3}/python/`) so
  `cdk synth` succeeds and the ARN-pinning contract is real; the actual
  wheel-building CI step is out of scope until a CodeBuild/CI phase exists
  to run it (this repo doesn't have `.github/workflows` CDK deploy
  automation yet either — see `docs/EXECUTION_STATE.txt`).

## Consequences

Deferred until later phases land and until a real AWS dev account exists
(tracked in `docs/EXECUTION_STATE.txt`, not silently dropped):

1. "Every listed Lambda deployed with correct memory/timeout/concurrency"
   — none of the 25 exist yet; each lands with its owning phase.
2. "Every role scoped without unresolved `*` (audit script)" — no audit
   script exists yet, and there are no per-registry roles yet to audit
   beyond `SentinelLambda`'s own boundary-scoped shape (verified here by
   cdk-nag).
3. "Cold start p95 ≤ 1.5s across the fleet" and "DLQs empty after 24-hour
   synthetic load" — both need a deployed fleet on a real AWS dev account.
4. The actual Powertools/boto3 layer *contents* — placeholder assets only,
   pending a CI/CodeBuild pipeline.

`LambdaStack`'s docstring already flagged (from phase-00) that it would
be "populated by aws-infra phase-04" — this ADR records that "populated"
means the shared substrate, not the registry's function bodies, and
points every future reader at this decision instead of re-litigating it
per specialist phase.
