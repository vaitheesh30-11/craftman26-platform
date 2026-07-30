# frontend/ — IAM Sentinel Governance Console

Next.js 14 App Router. Chat with Sentinel Prime, review findings, approve remediations with Zelkova evidence, watch platform dashboards.

Authoritative canon: `SYSTEM_STATE.md`, `docs/ARCHITECTURE.md`, `docs/DATA_CONTRACTS.md`, `backend/README.md`.

---

## 1. Module Purpose and System Boundaries

**Purpose.** A production-quality operator console. The frontend is optional for hackathon-only submissions (REST + WebSocket cover every workflow), but it is a strong differentiator during judging — demonstrating end-to-end usability.

**In scope.**
- Next.js 14 App Router (React Server Components where practical).
- Authenticated by AWS Amplify UI + Cognito hosted UI OAuth.
- Streaming chat console for Prime.
- Findings inbox with filters, drill-down, and evidence viewer.
- Remediation approval flow with Zelkova witness display.
- Platform dashboards (findings trend, cost, faults, breaker states).

**Out of scope.**
- Server-side data mutation (all state changes go through `backend/`).
- Any direct AWS SDK usage in the browser — Amplify handles auth tokens; app calls `backend/` only.

**Boundaries.**
- Consumes: `backend/` REST + WebSocket.
- Never talks to Bedrock, DDB, or S3 directly.

---

## 2. Directory Tree

```
frontend/
├── README.md                       this file
├── package.json                    Next.js 14, TypeScript
├── next.config.js
├── tailwind.config.ts
├── tsconfig.json
├── docs/
│   ├── README.md                   phase index
│   ├── phase-00-frontend-foundations.txt
│   ├── phase-01-chat-console.txt
│   ├── phase-02-findings-inbox.txt
│   ├── phase-03-remediation-approval.txt
│   └── phase-04-dashboards.txt
├── app/
│   ├── layout.tsx                  root layout with auth guard
│   ├── page.tsx                    landing
│   ├── (dashboard)/
│   │   ├── chat/page.tsx
│   │   ├── findings/page.tsx
│   │   ├── findings/[id]/page.tsx
│   │   ├── decisions/page.tsx
│   │   ├── decisions/[id]/page.tsx
│   │   ├── operations/page.tsx
│   │   └── reports/page.tsx
│   ├── api/
│   │   └── proxy/[...path]/route.ts  BFF proxy to backend
│   └── auth/
│       ├── login/page.tsx
│       └── callback/page.tsx
├── components/
│   ├── ui/                         shadcn/ui primitives
│   ├── chat/                       ChatConsole, ProgressLine, ResultBlock
│   ├── findings/                   FindingsTable, FindingDetail, SeverityBadge
│   ├── decisions/                  DecisionDetail, RemediationCard, ZelkovaWitness
│   ├── operations/                 HealthGrid, FaultsTable
│   └── layout/                     Sidebar, TopBar, AuthGate
├── lib/
│   ├── api-client.ts               typed client generated from OpenAPI
│   ├── websocket-client.ts
│   ├── auth.ts                     Amplify auth wrappers
│   └── format.ts                   ARN/policy prettifiers
├── public/
├── tests/
│   ├── unit/                       Vitest
│   ├── component/                  React Testing Library
│   └── e2e/                        Playwright
└── styles/
    └── globals.css
```

---

## 3. Tech Stack

- Next.js `14.2`, React 18, TypeScript 5.5.
- Tailwind CSS + `shadcn/ui` primitives.
- `@aws-amplify/ui-react` for Cognito hosted UI.
- TanStack Query for server state; Zustand for local UI state.
- `zod` for form validation.
- Vitest + Playwright for tests.
- MSW for local dev mocks.

Forbidden: any state library that duplicates server state (Redux for API data), UI kits other than shadcn/Tailwind primitives.

---

## 4. Contract with Backend

- Every API call goes through `lib/api-client.ts`, a typed client generated from `backend/`'s OpenAPI (via `openapi-typescript`).
- Chat uses `lib/websocket-client.ts`; PROGRESS lines render as an animated log; RESULT block renders as a structured DecisionRecord viewer.
- Auth token supplied via Amplify Auth session; the BFF proxy at `app/api/proxy/[...path]/route.ts` forwards to the backend and injects the bearer token server-side (so tokens never leave the origin).

---

## 5. Non-Functional Requirements

- LCP ≤ 2.5 s on 4G, TTI ≤ 3.5 s.
- WebSocket reconnect within 2 s on network flap.
- Accessibility: WCAG 2.2 AA baseline; keyboard-navigable; visible focus.
- No secrets in `public/`; no runtime env var leaks in JS bundle.

---

## 6. Acceptance Criteria (Module-Wide)

- [ ] `pnpm build` clean.
- [ ] `pnpm test` (unit + component) ≥ 85% covered on core components.
- [ ] `pnpm test:e2e` (Playwright) green on 4 golden flows: login, chat single-specialist, chat multi-specialist, approve remediation.
- [ ] Amplify auth end-to-end (Cognito hosted UI callback).
- [ ] axe-core zero violations at severity `serious` or higher.
