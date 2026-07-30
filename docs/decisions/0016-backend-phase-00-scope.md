# ADR 0016 — backend phase-00: Backend Foundations scope

Status: accepted
Date: 2026-07-31

## Context

`backend/docs/phase-00-backend-foundations.txt` is the first backend-module
phase in the sprint: the FastAPI-on-Lambda substrate (`create_app()` +
`Mangum` handler, auth middleware, adapter DI, error envelope, correlation
ID, `/health`) every later backend phase (REST routes, WebSocket streaming,
approval workflow, audit reports) builds on. Same shape of gap as every
prior "add on-demand" ADR (0006, 0014, 0015): the code is real and fully
testable offline; only one acceptance criterion needs a deployed Lambda
this sprint step doesn't provision (that's `aws-infra` phase-07, sprint
step 20, not yet built).

Three scoping decisions, plus one cross-module addition and one real bug
fixed along the way.

## Decision

- **§6 "App boots inside a Lambda container in < 800 ms cold-start" is not
  measured.** No `aws-infra` API Gateway/Lambda deployment target exists
  yet for this specific handler (`aws-infra` phase-07, `feat/aws-infra-api`,
  is sprint step 20 -- immediately after this one). The app factory is
  built for that budget regardless: `Mangum(app, lifespan="off")` skips
  ASGI lifespan probing per invocation, `docs_url`/`redoc_url` disable
  Swagger UI generation in `prod`, and every adapter dependency in
  `deps.py` is an `lru_cache(maxsize=1)` singleton constructed once per
  execution environment, not per request. Re-run and record the real
  number once `aws-infra` phase-07 deploys this Lambda.
- **`GET /health`'s `commit` field is a `BackendSettings.commit_sha`
  passthrough, not derived from `git rev-parse` at build time.** No CI
  packaging step exists yet to inject a build-time commit SHA into the
  Lambda's environment (that's part of `aws-infra` phase-07's deploy
  pipeline). Defaults to `"unknown"`; wire `SENTINEL_COMMIT_SHA` in that
  phase's Lambda environment block.
- **The SigV4 relay path (`auth/sigv4.py`'s `SigV4Verifier`) is verified
  against a mocked `requests.Session`, not a real STS endpoint.** Per the
  phase doc's own §7 risk table, the primary SigV4 path is API Gateway's
  IAM-auth pass-through (`from_apigw_identity`, which trusts
  `event.requestContext.identity.userArn` -- already verified upstream, no
  STS call at all); the relay path exists only for WebSocket auth and local
  dev, where no API Gateway sits in front of the request. Both paths are
  unit-tested against their actual verification logic; only the live
  network round-trip to `sts.<region>.amazonaws.com` is unverified, and
  that endpoint's request/response shape is a fixed, publicly documented
  AWS API surface, not something specific to this repo's infrastructure.

## Cross-module addition

`iam_sentinel_adapters.sts.StsClient` (`adapters/src/iam_sentinel_adapters/
sts.py`) is new in this phase: the SigV4 relay path needs
`sts:GetCallerIdentity`, and the boto3-only-through-adapters rule
(`adapters/README.md` §1) means that call cannot live inline in `backend/`.
Added on-demand for this consumer, same precedent ADR 0006 set for DDB
table clients ("add each on-demand when the specialist or backend phase
that needs it lands"). `StsClient.verify_signed_request` relays a caller-
presigned `GetCallerIdentity` request's headers to STS rather than
accepting raw access keys/secrets -- the same verification pattern
HashiCorp Vault's AWS auth method and `aws-iam-authenticator` use, so the
caller's secret key never reaches Sentinel. `StsClient.whoami` (real
`boto3.client("sts").get_caller_identity()`) resolves Sentinel's own
runtime identity and is unit-tested via moto/mocked boto3, no network
dependency.

## Consequences

1. §6 "cold-start < 800ms" -- deferred; design-bounded (`lifespan="off"`,
   singleton deps, no dev-mode docs generation in prod), not measured.
   Tracked in `docs/EXECUTION_STATE.txt` NOTES + BLOCKERS pending
   `aws-infra` phase-07.
2. §6 "/health returns 200 with no auth" -- met; `test_health_returns_200_
   with_no_auth`.
3. §6 "Auth middleware rejects unauthenticated requests with 401 (no leak
   of resource existence)" -- met; `test_get_principal_rejects_missing_
   authorization` returns a generic `UNAUTHENTICATED` code with no route-
   specific detail.
4. §6 "All error handlers wired" -- met; every domain exception in
   `iam_sentinel_adapters.errors` that phase-00 §4's table names maps to
   its documented status, plus `SentinelHTTPException` and the catch-all
   500 (`test_errors.py`, 6 cases).
5. §4 Step 6 "OpenAPI schema exported and compared to a golden file on
   PR" -- built, not deferred: `scripts/export_openapi.py`,
   `backend/openapi.golden.json`, `test_openapi_contract.py`, and a
   `contract` job in `.github/workflows/backend-ci.yml`. The golden file
   currently covers only `/health`; it grows with each router phase-01
   onward adds.

Note on a closure hazard avoided by construction, not caught after the
fact: `register_exception_handlers`'s per-exception-type handler
registration loop binds `code`/`http_status` through an explicit
`_make_handler(bound_code, bound_status)` factory rather than having the
inner `async def _handler` close directly over the loop variables --
Python's late-binding closures would otherwise make every domain
exception resolve to whichever `(code, http_status)` pair was last in
`_DOMAIN_EXCEPTION_STATUS`'s iteration order. `test_domain_exceptions_map_
to_the_documented_status_and_code`'s five parametrized cases exist
specifically to keep this from regressing if the loop is ever refactored.
