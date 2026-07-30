# ADR 0003 — aws-infra phase-01: defer an AWS Backup plan for `SentinelBreakGlassSessions`

Status: accepted
Date: 2026-07-30

## Context

`cdk-nag`'s HIPAA Security pack (wired in aws-infra phase-00 per that
phase's spec §6, enabled by default via `cdk.json`'s
`enable-hipaa-nag` flag) flags `HIPAA.Security-DynamoDBInBackupPlan` on
every DynamoDB table not enrolled in an AWS Backup plan.

Point-in-time recovery (35-day continuous backup) is enabled directly on
`SentinelBreakGlassSessions` in this phase, which satisfies the data-loss
concern for this table specifically. A full AWS Backup plan (vault, backup
plan, selection rules) is an account/organization-level resource whose
retention policy, vault lock, and cross-account copy behavior are shared
infrastructure decisions that should cover every Sentinel table at once
(the `SentinelFindings`, `SentinelDecisions`, and memory tables land in
aws-infra phase-02), not be decided piecemeal per table as each lands.

## Decision

Suppress `HIPAA.Security-DynamoDBInBackupPlan` on
`SentinelBreakGlassSessions` for this phase, with the justification above.
Track a single AWS Backup plan covering all Sentinel DynamoDB tables as a
follow-up once aws-infra phase-02 (`FoundationStack`) lands the rest of the
tables — track this in `docs/EXECUTION_STATE.txt` NOTES + BLOCKERS.

## Consequences

- `SentinelBreakGlassSessions` has PITR (35-day point-in-time recovery) but
  no long-term backup vault until the org-wide backup plan lands.
- The backup-plan gap must be closed before this platform could actually
  claim HIPAA-aligned controls in a real compliance review; today's
  HIPAA-pack usage is a security-hardening lint, not a compliance claim.
