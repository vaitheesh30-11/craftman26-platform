# ADR 0001 — aws-infra phase-01: defer the two live-account acceptance criteria

Status: accepted
Date: 2026-07-30

## Context

`aws-infra/docs/phase-01-security-stack.txt` §8 lists four acceptance criteria:

1. All 3 KMS keys created with correct policies.
2. Guardrail LIVE alias present and passes canary.
3. Break-glass drill passes end-to-end.
4. CloudTrail alarms fire in unit test with a simulated event.

No AWS dev account is provisioned yet (tracked in `docs/EXECUTION_STATE.txt`
NOTES + BLOCKERS). Criteria 2 and 3 require a real deployed stack: the
Guardrail canary invokes a LIVE Bedrock Guardrail alias, and the break-glass
drill requires real `sts:AssumeRole` calls across two distinct IAM
principals. Neither is reproducible with `cdk synth` or unit tests alone.

## Decision

Build every phase-01 deliverable to be code-complete and locally verified:

- `cdk synth` clean for all 8 stacks across dev/staging/prod.
- `cdk-nag` zero Error-severity findings.
- Unit tests for the real decision logic that ships in this phase: the
  Guardrail lifecycle Lambda's request routing, and the break-glass
  two-signer approval evaluator (distinct-principal + 60-second-window
  check).

Criteria 2 and 3 are deferred, not silently marked done. They are tracked
as an explicit open item in `docs/EXECUTION_STATE.txt` NOTES + BLOCKERS and
must be re-run once a dev account exists and the stack is actually
deployed, before this phase can be considered fully accepted.

## Consequences

- The phase merges to `main` and is tagged `phase/aws-infra-security-done`
  on the strength of criteria 1 and 4 (and the code for 2/3 existing and
  passing local checks), not on all four criteria being met.
- Whoever provisions the dev account must re-open this phase: deploy
  `SentinelSecurity`, run the Guardrail canary against the LIVE alias, and
  run a real two-signer break-glass drill, before the security posture can
  be considered production-verified.
