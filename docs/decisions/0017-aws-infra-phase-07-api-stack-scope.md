# ADR 0017 — aws-infra phase-07: API Stack scope

Status: accepted
Date: 2026-07-31

## Context

`aws-infra/docs/phase-07-api-stack.txt` asks for a REST API + WebSocket API
fronting `backend`'s FastAPI-on-Lambda app (phase-00, done), Cognito, a
Lambda authorizer, WAF, usage plans, and logging — all in a synth-only
sandbox with no live AWS account, matching every prior aws-infra phase's
constraint. Four genuine spec ambiguities needed a resolution before any
of this could be built; all four are architecture decisions, not testing
shortcuts, and are recorded here.

## Decisions

### 1. One Lambda authorizer serves both §6 bullets 1 and 2

§6 asks for "Cognito JWT authorizer on every path except `/health`" *and*
"IAM SigV4 auth accepted on the same paths for machine callers" — but an
API Gateway REST method carries exactly one `authorizationType`; native
`COGNITO_USER_POOLS` and native `AWS_IAM` cannot both apply to the same
method. `functions/api_authorizer/handler.py` is a single REQUEST
authorizer that inspects the `Authorization` header itself: a
`Bearer <token>` value is verified via `cognito-idp:GetUser` (delegating
verification to Cognito rather than re-implementing JWKS/RS256 locally —
see decision 2 for why); an `AWS4-HMAC-SHA256` value is relayed to STS as
a caller-presigned `GetCallerIdentity` request, mirroring
`iam_sentinel_backend.auth.sigv4.SigV4Verifier`'s already-documented
pattern. This is the deliverable explicitly named "Lambda authorizer for
machine callers (IAM-signed)" in §2, extended to also carry the Cognito
path so both bullets resolve to one authorizer instead of two mutually
exclusive native mechanisms.

### 2. The authorizer has zero third-party dependencies, by design

`backend`'s own `CognitoJwtVerifier` needs PyJWT + `cryptography` for
local RS256/JWKS verification. Every prior aws-infra Lambda
(`guardrail_lifecycle`, `crossaccount_drift_detector`, …) ships with only
the shared `boto3`/`powertools` layers — `functions/layers/*/python/` are
still empty `.gitkeep` placeholders (ADR 0011, ADR 0015), and adding PyJWT
would need a third layer nothing in this repo yet builds. Delegating token
verification to `cognito-idp:GetUser` (which raises on any
expired/invalid/revoked access token) gets a real, AWS-verified answer
with zero extra dependencies. Trade-off: callers must present the Cognito
**access token**, not the ID token, as `Authorization: Bearer <token>` —
acceptable since the authorizer only needs identity, not ID-token claims
(`backend`'s own routers, once they exist in phase-01, still verify the
ID token again internally via `CognitoJwtVerifier` for claim-level
authorization decisions).

### 3. `/emergency/*` is gated by an IAM resource-policy condition, not the Lambda authorizer

`iam_sentinel_backend.auth.breakglass` documents trusting a *reflected*
break-glass session tag rather than re-deriving it — but there is no AWS
read API that recovers an arbitrary caller's *session* tags
(`aws:PrincipalTag/*`) after the fact: `sts:GetCallerIdentity` returns only
`Arn`/`Account`/`UserId`, and session tags are transient AssumeRole-time
state, not queryable via `iam:GetRole`/`iam:ListRoleTags` (those return the
role's own persistent tags, a different thing). The only AWS mechanism
that can actually evaluate `aws:PrincipalTag/BreakGlass` is IAM itself, at
the moment a request is authorized — which means `/emergency/*` must use
native `AuthorizationType.IAM`, with a resource-policy `Deny` on
`execute-api:Invoke` for that path unless
`aws:PrincipalTag/BreakGlass = IAMSentinel-Two-Signer` is present. This is
implemented in `api_stack.py::_apply_emergency_resource_policy`. The
`X-BreakGlass-Session-Tag` header `backend`'s `verify_breakglass_header`
checks becomes defense-in-depth for direct-invoke/local testing, not the
live enforcement point — the live enforcement is this IAM condition,
evaluated before the request ever reaches Lambda. `breakglass.py`'s
docstring is accurate about *what* gets trusted; this ADR documents *how*
that trust is actually established at the AWS layer.

### 4. `backend`'s Lambda deployment package is a placeholder shim, not a real bundle

Provisioning `SentinelApi`'s Lambda integration is this phase's job, but
*packaging* `backend`'s dependency closure (`fastapi`, `mangum`,
`pydantic`, `requests`, `iam_sentinel_adapters`) into a deployable zip is
the same unresolved pip-bundling gap ADR 0011 and ADR 0015 already
flagged — no CI layer-build pipeline or Docker-bundled `PythonFunction`
exists in this repo yet. `functions/backend_api/handler.py` is a real,
tested shim: it imports `iam_sentinel_backend.app.handler` if available and
returns a deterministic `502 BACKEND_NOT_PACKAGED` if not, rather than
either faking a working integration or leaving the phase's central
Lambda unbuilt. CDK wiring (the `Function`, the `LambdaIntegration`, SSM
params, IAM role) is 100% real; only the deployment artifact's actual
dependency contents are deferred. Whoever solves the packaging gap points
`functions/backend_api/`'s asset at a bundled build output (or swaps to
`aws_cdk.aws_lambda_python_alpha.PythonFunction`) and deletes the
try/except fallback.

### Scoped out per the spec's own wording

- **Custom domain + ACM cert** — §2 marks this "(optional)"; no domain name
  or hosted zone exists in `StageConfig` yet (frontend phase-00, sprint
  step 24, hasn't landed). Skipped, not deferred with an open criterion.
- **Cognito Identity Pool** — §5 marks this "(optional) if we need direct-
  AWS-credential exchange for privileged UI flows"; no frontend flow needs
  it yet. Skipped for the same reason.
- **Cognito WebAuthn (passkey) MFA** — §5 asks for "TOTP + WebAuthn"; the
  pinned `aws-cdk-lib==2.163.0`'s `UserPool` L2 only exposes
  `MfaSecondFactor(otp, sms)`, no WebAuthn option (Cognito's own WebAuthn
  MFA feature is newer than this CDK pin's L2 coverage). `mfa=REQUIRED` +
  TOTP ships; WebAuthn needs either a newer CDK or an L1 escape hatch once
  CloudFormation itself exposes the property — tracked here, not silently
  dropped.
- **Access logs to S3** — §8 says access logs stream to
  `SentinelAccessLogs-{stage}` (a bucket). API Gateway's native access-log
  destination is a CloudWatch Logs log group, not S3 directly (S3 delivery
  needs a Firehose subscription hop). Implemented as a `logs.LogGroup`
  with the documented retention (14d dev/staging, 90d prod); the S3 hop is
  deferred as a follow-on, not built speculatively.

## Consequences

1. `/emergency/*`'s break-glass enforcement cannot be exercised end-to-end
   without a real two-signer STS session carrying the actual
   `aws:PrincipalTag/BreakGlass` tag — same live-AWS gap `docs/decisions/
   0001` already opened for aws-infra phase-01's break-glass drill.
   Tracked in `docs/EXECUTION_STATE.txt` NOTES + BLOCKERS.
2. The Cognito access-token authorizer path is unverified against a real
   User Pool (needs a deployed pool + an actual issued access token); unit
   tests mock `cognito-idp:GetUser`'s success/`ClientError` shapes instead.
3. `backend_api`'s shim means `SentinelApi` synths and its IAM/routing
   shape is fully testable, but a live `curl` against a deployed stage
   returns `502 BACKEND_NOT_PACKAGED` until the packaging gap closes —
   §9's "hit every route with a curl + Cognito token" integration test
   plan is deferred with everything else that needs a real account.
4. `SentinelStream`'s `$default` route only acknowledges frames; real
   Prime-turn streaming fan-out is `backend` phase-02's deliverable
   (sprint step 22). §10's "WebSocket streaming end-to-end works from the
   frontend" acceptance criterion is deferred to that phase.
