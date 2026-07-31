import { http, HttpResponse } from "msw";

// Matched against absolute `BACKEND_ORIGIN` URLs, not `/api/proxy/*` — the
// BFF proxy route (`app/api/proxy/[...path]/route.ts`) is real code that
// always runs; only its outbound call to the FastAPI backend is mocked
// (see `mocks/server-bootstrap.ts`). This exercises the proxy's own auth/
// CSRF/correlation-id logic for real while still needing zero live AWS.
const BACKEND_ORIGIN = process.env.BACKEND_ORIGIN ?? "http://localhost:8000";

// `lib/env.ts` defaults `NEXT_PUBLIC_COGNITO_DOMAIN` to this exact host when
// no `.env.local` is present, so the OAuth code-exchange round trip
// (`app/auth/callback/route.ts` -> `lib/auth.ts#exchangeCodeForTokens`)
// works end-to-end in local dev / CI e2e with zero real Cognito pool.
const COGNITO_DOMAIN = process.env.NEXT_PUBLIC_COGNITO_DOMAIN ?? "local-dev.auth.invalid";

const nowIso = () => new Date().toISOString();

export const handlers = [
  http.post(`https://${COGNITO_DOMAIN}/oauth2/token`, () =>
    HttpResponse.json({
      access_token: "mock-access-token",
      id_token: "mock-id-token",
      refresh_token: "mock-refresh-token",
      token_type: "Bearer",
      expires_in: 3600,
    }),
  ),

  http.get(`${BACKEND_ORIGIN}/health`, () =>
    HttpResponse.json({ ok: true, data: { stage: "dev", commit: "mock" } }),
  ),

  http.get(`${BACKEND_ORIGIN}/findings`, () =>
    HttpResponse.json({
      ok: true,
      data: {
        items: [
          {
            finding_id: "01JBQXMOCK0000000000000001",
            feature_id: "F1",
            account_id: "111122223333",
            principal_arn: "arn:aws:iam::111122223333:role/example-role",
            resource_arn: null,
            severity: "HIGH",
            title: "Wildcard PassRole grant reaches an admin-equivalent role",
            detail: "example-role can PassRole into blast-radius CRITICAL targets.",
            aws_doc_citation: {
              gap_id: "F1",
              quote:
                "You must grant iam:PassRole for the specific roles you want to allow.",
              source: "IAM User Guide",
              url: "https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_use_passrole.html",
              retrieved_on: "2026-07-01",
            },
            payload: {},
            detected_at: nowIso(),
            expires_at: null,
            evidence_ref: null,
            status: "OPEN",
          },
        ],
        next_token: null,
      },
    }),
  ),

  http.get(`${BACKEND_ORIGIN}/findings/:findingId`, ({ params }) =>
    HttpResponse.json({
      ok: true,
      data: {
        finding_id: params.findingId,
        feature_id: "F1",
        account_id: "111122223333",
        principal_arn: null,
        resource_arn: null,
        severity: "MEDIUM",
        title: "Mock finding detail",
        detail: "MSW-backed local dev fixture.",
        aws_doc_citation: {
          gap_id: "F1",
          quote: "Mock citation quote.",
          source: "IAM User Guide",
          url: "https://docs.aws.amazon.com/IAM/latest/UserGuide/",
          retrieved_on: "2026-07-01",
        },
        payload: {},
        detected_at: nowIso(),
        expires_at: null,
        evidence_ref: null,
        status: "OPEN",
      },
    }),
  ),

  http.get(`${BACKEND_ORIGIN}/decisions`, () =>
    HttpResponse.json({
      ok: true,
      data: {
        items: [
          {
            decision_id: "01JBQXMOCK0000000000000005",
            correlation_id: "01JBQXMOCK0000000000000006",
            principal: "arn:aws:iam::111122223333:user/dev",
            query: {},
            specialist_verdicts: [],
            findings: [],
            remediations_proposed: [],
            remediations_applied: [],
            status: "ANSWERED",
            narrative: "Reviewed PassRole exposure for example-role.",
            evidence_ref: {},
            decided_at: nowIso(),
          },
        ],
        next_token: null,
      },
    }),
  ),

  http.get(`${BACKEND_ORIGIN}/decisions/:decisionId`, ({ params }) =>
    HttpResponse.json({
      ok: true,
      data: {
        decision_id: params.decisionId,
        correlation_id: "01JBQXMOCK0000000000000002",
        principal: "arn:aws:iam::111122223333:user/dev",
        query: {},
        specialist_verdicts: [],
        findings: [],
        remediations_proposed: [],
        remediations_applied: [],
        status: "ANSWERED",
        narrative: "Mock decision narrative for local dev.",
        evidence_ref: {},
        decided_at: nowIso(),
      },
    }),
  ),

  http.post(`${BACKEND_ORIGIN}/agent/chat`, () =>
    HttpResponse.json({
      ok: true,
      data: {
        decision_id: "01JBQXMOCK0000000000000003",
        correlation_id: "01JBQXMOCK0000000000000004",
        principal: "arn:aws:iam::111122223333:user/dev",
        query: {},
        specialist_verdicts: [],
        findings: [],
        remediations_proposed: [],
        remediations_applied: [],
        status: "ANSWERED",
        narrative: "This is a mocked Prime response for local development.",
        evidence_ref: {},
        decided_at: nowIso(),
      },
    }),
  ),

  http.get(`${BACKEND_ORIGIN}/operations/faults`, () =>
    HttpResponse.json({ ok: true, data: { items: [], next_token: null } }),
  ),
];
