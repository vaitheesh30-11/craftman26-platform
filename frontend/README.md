# frontend/ — Enterprise Governance Dashboard

Next.js 14 App Router application that renders the Sentinel-IQ v8 governance dashboard. Consumes `backend/` via REST + WebSocket per `docs/API_SPEC.md`. Renders `DecisionRecord`, `DiffArtifact`, and `SpecialistVerdict` per `docs/DATA_CONTRACTS.md`.

---

## 1. Module Purpose and System Boundaries

**Purpose**. Give SOC analysts, security engineers, and auditors a real-time view of enterprise drift, Council reasoning, and human-in-the-loop approval gates.

**In scope**:
- All UI routes (`/`, `/drift`, `/baseline`).
- WebSocket subscription to `/ws/drift`.
- REST calls to `/api/v1/*`.
- Human-in-the-loop approval flows.
- Baseline viewer.

**Out of scope**:
- Any direct AWS API calls (backend proxies everything).
- Any Bedrock invocation (agents own this).
- Any evidence writes (Executor Lambda owns this).

**Boundaries with other modules**:
- Input: REST + WebSocket from `backend/`.
- Output: user actions POSTed to `backend/`.
- Never imports from `agents/`, `adapters/`, `aws-infra/`.

---

## 2. Files and Directory Tree to Generate

```
frontend/
├── package.json
├── tsconfig.json
├── next.config.mjs
├── tailwind.config.ts
├── postcss.config.mjs
├── .env.example
├── app/
│   ├── layout.tsx                  Root layout with nav shell + theme
│   ├── page.tsx                    "/" dashboard overview
│   ├── globals.css
│   ├── drift/
│   │   ├── page.tsx                Paginated drift feed
│   │   └── [id]/
│   │       └── page.tsx            Single-drift deep dive
│   ├── baseline/
│   │   └── page.tsx                Baseline viewer + upload
│   └── api/
│       └── health/
│           └── route.ts            Frontend health endpoint (for probes)
├── components/
│   ├── drift-feed-card.tsx
│   ├── council-modal.tsx
│   ├── approval-modal.tsx
│   ├── zelkova-badge.tsx
│   ├── severity-chip.tsx
│   ├── action-badge.tsx
│   ├── evidence-link.tsx
│   ├── baseline-tree.tsx
│   └── layout/
│       ├── nav-shell.tsx
│       └── theme-provider.tsx
├── hooks/
│   ├── use-drift-socket.ts         WebSocket subscription hook
│   ├── use-drift-feed.ts           REST paginated feed hook
│   ├── use-decision.ts             Single-decision hook
│   └── use-baseline.ts             Baseline read + upload
├── lib/
│   ├── api-client.ts               Typed REST client
│   ├── ws-client.ts                Typed WebSocket helper (used by hook)
│   ├── auth.ts                     Cognito auth wrapper
│   ├── errors.ts                   Error envelope decoder
│   └── formatters.ts               Timestamp, byte, ARN formatters
├── types/
│   └── contracts.ts                TS declarations mirroring docs/DATA_CONTRACTS.md
└── __tests__/                      Vitest + React Testing Library
    ├── drift-feed-card.test.tsx
    ├── council-modal.test.tsx
    └── use-drift-socket.test.ts
```

---

## 3. Tech Stack and Recommended Libraries

- Next.js 14 App Router (React 18 Server Components + Client Components).
- TypeScript 5.5+ in `strict` mode.
- Tailwind CSS + `class-variance-authority` for component variants.
- shadcn/ui for primitive components (button, dialog, badge, tabs).
- TanStack Query v5 for REST caching and mutation state.
- Zod v3 for runtime validation of API responses.
- Cognito Hosted UI + `aws-amplify/auth` (or a lightweight OIDC client) for auth.
- Vitest + React Testing Library for unit tests.
- Playwright for E2E (Epic 7.8 scenarios).

Do NOT introduce: Redux, Zustand, MobX, Apollo, or any bespoke state manager. TanStack Query + React state suffice.

---

## 4. Step-by-Step Implementation Instructions

### 4.1 Bootstrap
1. `pnpm create next-app@latest frontend --ts --tailwind --app --no-eslint --no-src-dir`.
2. Add scripts: `dev`, `build`, `start`, `typecheck`, `test`, `test:e2e`.
3. Set `next.config.mjs` `output: 'standalone'` for Docker/Lambda targets.

### 4.2 Types
1. Copy the four contract shapes from `docs/DATA_CONTRACTS.md` into `types/contracts.ts` as TypeScript interfaces with exported Zod schemas.
2. Every response parser in `lib/api-client.ts` MUST validate via Zod before returning.

### 4.3 API + WebSocket clients
1. `lib/api-client.ts` uses `fetch` with an interceptor that adds `Authorization: Bearer <cognitoJwt>`.
2. On non-2xx, decode via `lib/errors.ts` and throw a typed `ApiError`.
3. `lib/ws-client.ts` exposes `connectDriftSocket({ subscribeTo })` that returns an `EventEmitter`-shaped object.
4. `hooks/use-drift-socket.ts` wraps that with React state, reconnect backoff (1s, 2s, 5s, 15s, 60s), and ping/pong handling per `docs/API_SPEC.md` section 7.

### 4.4 Layout and routing
1. `app/layout.tsx`: theme provider, nav shell, error boundary, TanStack Query provider.
2. `app/page.tsx`: overview cards (drift-rate, autonomous-remediation-rate, dissent-rate).
3. `app/drift/page.tsx`: renders `drift-feed-card` per row using `use-drift-feed`.
4. `app/drift/[id]/page.tsx`: fetches deep dive, embeds `council-modal` inline.
5. `app/baseline/page.tsx`: baseline viewer + upload modal.

### 4.5 Components (contracts)
- `drift-feed-card` props: `{ diffArtifact: DiffArtifact; latestDecision?: DecisionRecord; onOpenReasoning: () => void }`.
- `council-modal` props: `{ decisionId: string; open: boolean; onClose: () => void }`. Fetches the deep dive on open.
- `approval-modal` props: `{ decisionId: string; callbackToken: string; requiresTwoSigners: boolean; onResolved: (state) => void }`.
- `zelkova-badge` props: `{ preCheck?: ZelkovaResult; postCheck?: ZelkovaResult; polling?: boolean }`.

### 4.6 Real-time integration
1. Root layout mounts `useDriftSocket({ subscribeTo: ['DRIFT_DETECTED','DECISION_EMITTED','REMEDIATION_COMPLETE','VERIFICATION_FAILED'] })`.
2. On `DRIFT_DETECTED`: prepend to the feed cache; toast if severity ≥ high.
3. On `DECISION_EMITTED`: patch the affected drift entry with the new decision.
4. On `REMEDIATION_COMPLETE`: patch the entry with `zelkovaPostCheck.pass = true`.
5. On `VERIFICATION_FAILED`: red-toast, expand card, force the user to acknowledge.

### 4.7 Error handling
- Every mutation goes through `useMutation` with an `onError` that surfaces the `ApiError.code` humanized via `lib/errors.ts`.
- WebSocket unauthenticated close code (`4401`) triggers Cognito token refresh; on second failure, redirects to login.

### 4.8 Accessibility
- All modals use `dialog` with focus trap.
- Colorblind-safe severity palette (do not rely solely on hue).
- Keyboard shortcuts documented in `/help` (deferred to Epic 8+).

---

## 5. Exact Codex Prompts

Paste these into your AI coding assistant with `frontend/` open as the working directory.

**Prompt A — Bootstrap and types**
> Read `docs/DATA_CONTRACTS.md` sections 1-4 and generate `frontend/types/contracts.ts` containing TypeScript interfaces and Zod schemas for `DiffArtifact`, `SpecialistVerdict`, `DecisionRecord`, `IntentBaseline`. Enum values must exactly match the doc. Add unit tests in `frontend/__tests__/contracts.test.ts` that fuzz-validate at least 10 fixtures per model.

**Prompt B — API client**
> Read `docs/API_SPEC.md`. Generate `frontend/lib/api-client.ts` and `frontend/lib/errors.ts`. Every endpoint in sections 1-6 must have a typed function. Every response must be Zod-validated against `frontend/types/contracts.ts`. Add unit tests that mock `fetch` and assert error envelope decoding.

**Prompt C — WebSocket hook**
> Read `docs/API_SPEC.md` section 7. Generate `frontend/lib/ws-client.ts` and `frontend/hooks/use-drift-socket.ts`. Handle handshake, ping/pong (30 s server → 10 s pong deadline), exponential reconnect (1,2,5,15,60 s), auth token refresh on close code `4401`, and typed emission of the four event frames. Add Vitest tests using `ws` mock server.

**Prompt D — Feed page**
> Generate `frontend/app/drift/page.tsx` and `frontend/hooks/use-drift-feed.ts` using TanStack Query cursor-based infinite pagination against `GET /api/v1/drift`. Render each row with `frontend/components/drift-feed-card.tsx`. Filters (severity, driftSurface, accountId, since) preserve URL search params. Add Vitest tests for the card and Playwright test for the page.

**Prompt E — Council reasoning modal**
> Generate `frontend/components/council-modal.tsx` per section 6.4 of `docs/EPICS_AND_STORIES.md`. Fetch `GET /api/v1/drift/{id}` on open. Render each of the four `SpecialistVerdict` outputs with agent-specific structured findings, highlight dissenting opinions, and link cited evidence ids to `/evidence/{id}`. Include `zelkova-badge` for pre/post results.

**Prompt F — Approval flow**
> Generate `frontend/components/approval-modal.tsx`. For Tier-0 resources, require two distinct approver identities before enabling the submit button. POST to `/api/v1/decisions/{id}/approve` with the callback token. Handle 409/410 gracefully. Include a Playwright test covering the two-signer requirement.

**Prompt G — Baseline viewer**
> Generate `frontend/app/baseline/page.tsx` per Epic 6.7. Fetch active baseline, render JSON with syntax highlighting, show a diff panel vs the immediately-prior version. Add an upload modal that validates the KMS-signed payload client-side (schema only; signature verification is server-side).

---

## 6. Inputs, Outputs, and Integration Boundaries

**Inputs**:
- REST GET responses from `backend/`.
- WebSocket events on `/ws/drift`.
- Cognito user session.

**Outputs**:
- REST POST bodies for `/decisions/{id}/approve` and `/baselines`.
- User telemetry via CloudWatch RUM (deferred to Epic 8+).

**Integration**:
- Every payload MUST be Zod-validated at the boundary. Any parse failure surfaces as a user-visible toast plus a Sentry-style error report.
- Never call AWS APIs directly. Always go through `backend/`.

---

## 7. Acceptance Criteria and Validation Commands

- `pnpm --filter frontend typecheck` passes.
- `pnpm --filter frontend test` passes with ≥ 80 percent line coverage on `hooks/`, `lib/`, and `components/`.
- `pnpm --filter frontend build` produces a working standalone build.
- `pnpm --filter frontend test:e2e` passes the three demo scenarios from `docs/EPICS_AND_STORIES.md` Epic 7.8.
- Lighthouse accessibility score ≥ 95 on `/`, `/drift`, `/baseline`.
- No TypeScript `any` outside typed-narrowing helpers.
