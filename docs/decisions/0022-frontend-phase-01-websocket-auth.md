# ADR 0022 — Frontend phase-01: WebSocket auth via a same-origin token mint, not the browser holding a bearer token

## Status
Accepted, with one cross-phase gap left open (see Consequences).

## Context
`aws-infra`'s `SentinelStream` WebSocket API (`aws-infra/src/iam_sentinel_infra/stacks/api_stack.py`,
phase-07) authorizes `$connect` via a `WebSocketLambdaAuthorizer` whose
`identity_source` is `route.request.header.Authorization` — a real HTTP
header on the WebSocket upgrade request.

Browsers cannot set arbitrary headers on a WebSocket handshake; the
`WebSocket` constructor only accepts a URL and an optional list of
subprotocols. This means, as currently deployed, **no browser client can
ever successfully complete `$connect`** — a pre-existing gap between
`aws-infra` phase-07/`backend` phase-02 and any real frontend consumer,
discovered here rather than caused by this phase.

Separately, phase-00's core security decision (`docs/decisions/`
precedent, `lib/session.ts`) is that the Cognito access token never
reaches client JS — it's sealed in a signed HttpOnly cookie the browser
can't read. A WebSocket connection is opened directly by browser JS
(`new WebSocket(url)`), which has no mechanism to attach an HttpOnly
cookie's value as a header or subprotocol either.

## Decision
1. `app/api/ws-token/route.ts`: a new, minimal same-origin Route Handler
   that reads the caller's own session cookie server-side (via
   `lib/current-session.ts`, the exact same trust boundary
   `AuthGate` uses) and returns `{ token: accessToken }` — nothing else,
   and only to the cookie's own owner. `lib/websocket-client.ts`'s
   connect flow fetches this once, immediately before opening the socket,
   and holds the token only in memory for the life of that connection —
   never in `localStorage`, never logged.
2. The socket is then opened as `${NEXT_PUBLIC_WS_URL}?token=<token>`
   (query string, not a header) — the one transport browsers can
   actually control on a WS handshake.
3. `NEXT_PUBLIC_WS_URL` is a new public env var (`lib/env.ts`), defaulted
   for zero-config local dev like every other phase-00 env var. Its real
   value in a deployed environment is `aws-infra`'s published
   `/sentinel/{stage}/api/websocket/url` SSM parameter — wiring that into
   a build-time env var is a deploy-pipeline concern, not this phase's.

## Consequences
- **Left open, not fixed here**: `aws-infra`'s `WebSocketLambdaAuthorizer`
  still reads `route.request.header.Authorization`. Nothing this phase
  builds can make a real deployed connection succeed until a future
  aws-infra change repoints `identity_source` to
  `route.request.querystring.token` (matching the query-string scheme
  this ADR picks) and the authorizer Lambda reads from there instead.
  Recorded in `docs/EXECUTION_STATE.txt` NOTES + BLOCKERS as a follow-up
  for whichever phase next touches `aws-infra`'s WebSocket auth wiring —
  out of scope for a frontend-only phase to change infra it doesn't own.
- Putting a bearer token in a URL is a known trade-off (it can land in
  server access logs, browser history for `wss://`, and `Referer`
  headers if navigated rather than opened via `WebSocket`). Scope is
  narrowed deliberately: `/api/ws-token` is same-origin-only, the token
  is the short-lived Cognito *access* token (never the refresh token),
  and it is used exactly once, in-memory, per connection attempt — the
  same trade-off AWS's own AppSync/IoT Core realtime SDKs accept for
  browser WebSocket auth.
- Local dev and CI have no deployed `SentinelStream` to connect to; the
  chat page's live-connection path is therefore unverifiable end-to-end
  until a real AWS dev account exists (same category of deferral as
  every other live-AWS criterion in `docs/EXECUTION_STATE.txt`). Unit
  tests inject a mock `WebSocket`; the Playwright spec uses
  `page.routeWebSocket()` to intercept the real `WebSocket` constructor
  call at the browser network layer, so the actual `lib/websocket-client.ts`
  code runs end-to-end against a scripted mock server, not a stub.
