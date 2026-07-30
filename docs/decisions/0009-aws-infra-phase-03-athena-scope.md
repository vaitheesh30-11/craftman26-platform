# ADR 0009 — aws-infra phase-03: Athena stack scope, Iceberg bootstrap, deferred criteria

Status: accepted
Date: 2026-07-30

## Context

`aws-infra/docs/phase-03-athena-stack.txt` §4 names the workgroup `sentinel`.
`agents/docs/phase-04-data-event-enricher.txt` §Step 2 (F3, the workgroup's
first real consumer, not built until Wave 3) names it `sentinel-f3`. Both
docs are canon; they disagree.

The raw `cloudtrail_logs` table (§3) is a plain Hive/SerDe external table
over JSON files that already exist in the org trail bucket — CloudFormation
`AWS::Glue::Table` can declare it directly. The optional curated
`writes_curated` table (§5) is Iceberg. Iceberg tables need real
`metadata.json` + manifest-list files that only an engine implementing the
Iceberg spec can produce; `AWS::Glue::Table` cannot bootstrap that from a
CloudFormation property bag alone.

Neither the raw table nor the curated table can be verified end-to-end
without a real AWS dev account: `cloudtrail_logs` is a projection over an
org CloudTrail bucket that doesn't exist in this environment (no org
account, no trail, no data), and `writes_curated` needs a workgroup that
can actually execute Athena queries against that data.

## Decision

- **Workgroup name**: `sentinel`, per this phase's own spec (the
  authoritative document for this stack). `agents/docs/phase-04...txt`'s
  `sentinel-f3` should be reconciled to `sentinel` when agents phase-04
  lands (Wave 3) — flagged here rather than silently diverging twice.
- **`org_trail_bucket_name`**: added to `StageConfig` (with a placeholder
  default, matching `org_id`/`org_root_id`'s existing placeholder
  convention) since neither phase doc's spec nor any prior phase
  provisions or names the org trail bucket — it's an external, not-yet-real
  resource this stack only references.
- **Iceberg bootstrap**: `writes_curated` is created by a CloudFormation
  custom-resource Lambda (`functions/athena_bootstrap`) that runs
  `CREATE TABLE ... WITH (table_type='ICEBERG', ...)` through Athena itself
  on `Create`/`Update`, idempotently (skips if `glue:GetTable` already
  finds it). This is the same lifecycle-Lambda pattern already used twice
  in this repo (`GuardrailCustomResource`, `oss_index_bootstrap`) for
  resources CloudFormation has no native support for.
- **Pre-flight trail-bucket check** (§9 risk mitigation): folded into the
  same bootstrap Lambda — it calls `s3:HeadBucket` on the org trail bucket
  before doing anything else and fails the custom resource (hence the
  deploy) if that call errors. This can only be a partial mitigation until
  a real org trail bucket with a real cross-account bucket policy exists.
- **IAM (§6)**: `AthenaStack.grant_query_access(role, write=...)` is a
  public method, not applied to any specialist role directly — F3/F4/F6
  don't exist until `LambdaStack` (aws-infra phase-04, already declared as
  a downstream dependency of `AthenaStack` in `app_factory.build_app`).
  The curate Lambda built in this phase calls it on its own role
  (`write=True`) as the first real caller.
- **Testing**: `functions/athena_bootstrap/handler.py` and
  `functions/athena_curate_writes/handler.py` are both named `handler.py`
  (matching this repo's Lambda-asset convention: every function's CDK
  `Code.from_asset` handler is `"handler.handler"`). Adding both
  directories to `pytest`'s `pythonpath` (as done for
  `guardrail_lifecycle`/`break_glass`) would make `import handler` resolve
  to whichever module pytest's import cache loaded first for both test
  files — the same collision aws-infra phase-02 already hit with mypy
  (see `EXECUTION_STATE.txt` HISTORY), just in pytest's import machinery
  instead. `pyproject.toml`'s `pythonpath` list is left unchanged; both new
  test files load their handler module via `importlib.util.spec_from_file_location`
  under a unique module name instead.

## Consequences

Deferred until a real AWS dev account exists with an org trail actually
delivering CloudTrail logs (tracked in `docs/EXECUTION_STATE.txt`, not
silently skipped) — all three of phase-03 §8's acceptance criteria:

1. "Sample query returns rows for a known account+day partition" — no real
   trail data exists yet.
2. "100 GB `BytesScannedCutoff` enforced (verified with a deliberately
   over-broad query)" — verified in this phase only as a static config
   assertion (`test_workgroup_enforces_the_100gb_scan_cap_and_sse_kms_encryption`);
   the *enforcement* itself is an Athena runtime behavior, not something
   `cdk synth`/unit tests can trigger.
3. "Curate Lambda writes to Iceberg table successfully" — needs a
   deployed workgroup + populated raw table to `INSERT INTO`.

Also open: whether `agents` phase-04 (Wave 3) should rename its
`sentinel-f3` workgroup reference to `sentinel` when it lands, per the
naming decision above.
