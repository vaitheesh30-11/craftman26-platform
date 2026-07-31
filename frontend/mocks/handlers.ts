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

  // Realistic fixture set for the findings inbox (phase-02): spans several
  // severities/features/accounts so `FindingsFilters`' severity/feature
  // multi-select and the account/since filters all have something to do in
  // local dev, and three distinct `evidence_ref` shapes (valid, tampered,
  // missing) that line up with the `/evidence/:ref` handlers below --
  // together they cover phase-02 §8's "3 fixture scenarios" criterion.
  http.get(`${BACKEND_ORIGIN}/findings`, ({ request }) => {
    const url = new URL(request.url);
    const severity = url.searchParams.get("severity");
    const featureId = url.searchParams.get("feature_id");
    const accountId = url.searchParams.get("account_id");

    const allFindings = [
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
          quote: "You must grant iam:PassRole for the specific roles you want to allow.",
          source: "IAM User Guide",
          url: "https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_use_passrole.html",
          retrieved_on: "2026-07-01",
        },
        payload: { blast_path: ["role/example-role", "role/deploy-orchestrator", "role/OrganizationAccountAccessRole"] },
        detected_at: nowIso(),
        expires_at: null,
        evidence_ref: { sha256: "mock-evidence-valid" },
        status: "OPEN",
      },
      {
        finding_id: "01JBQXMOCK0000000000000002",
        feature_id: "F6",
        account_id: "444455556666",
        principal_arn: "arn:aws:iam::444455556666:role/shadow-admin",
        resource_arn: null,
        severity: "CRITICAL",
        title: "Management account principal bypassed SCP guardrail",
        detail: "shadow-admin performed an action SCP Sentinel expected to be denied.",
        aws_doc_citation: {
          gap_id: "F6",
          quote: "Service control policies (SCPs) don't affect users or roles in the management account.",
          source: "AWS Organizations User Guide",
          url: "https://docs.aws.amazon.com/organizations/latest/userguide/orgs_manage_policies_scps.html",
          retrieved_on: "2026-07-01",
        },
        payload: {},
        detected_at: nowIso(),
        expires_at: null,
        evidence_ref: { sha256: "mock-evidence-tampered" },
        status: "OPEN",
      },
      {
        finding_id: "01JBQXMOCK0000000000000003",
        feature_id: "F3",
        account_id: "111122223333",
        principal_arn: null,
        resource_arn: "arn:aws:s3:::example-data-bucket",
        severity: "MEDIUM",
        title: "S3 bucket policy merge exceeds recommended size",
        detail: "example-data-bucket's merged bucket policy is close to the 20 KB service limit.",
        aws_doc_citation: {
          gap_id: "F3",
          quote: "Bucket policies are limited to 20 KB in size.",
          source: "Amazon S3 User Guide",
          url: "https://docs.aws.amazon.com/AmazonS3/latest/userguide/bucket-policies.html",
          retrieved_on: "2026-07-01",
        },
        payload: { merged_policy: { Version: "2012-10-17", Statement: [] }, size_bytes: 18432 },
        detected_at: nowIso(),
        expires_at: null,
        evidence_ref: null,
        status: "OPEN",
      },
    ];

    const items = allFindings
      .filter((f) => !severity || f.severity === severity)
      .filter((f) => !featureId || f.feature_id === featureId)
      .filter((f) => !accountId || f.account_id === accountId);

    return HttpResponse.json({ ok: true, data: { items, next_token: null } });
  }),

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

  // `GET /evidence/:ref` (backend phase-04) doesn't exist yet -- these two
  // fixture refs give `EvidenceViewer` something to exercise the "verified"
  // and "TAMPERED" states against locally; any other ref 404s, which
  // exercises its "missing" state (phase-02 §8 acceptance criterion).
  http.get(`${BACKEND_ORIGIN}/evidence/mock-evidence-valid`, () =>
    HttpResponse.json({
      ok: true,
      data: {
        ref: "mock-evidence-valid",
        kind: "specialist_output",
        correlation_id: "01JBQXMOCK0000000000000010",
        feature_id: "F1",
        body: { verdict: "CONFIRM", targets_evaluated: 3, blast_radius: "CRITICAL" },
        sha256: "mock-evidence-valid",
        verified: true,
      },
    }),
  ),

  http.get(`${BACKEND_ORIGIN}/evidence/mock-evidence-tampered`, () =>
    HttpResponse.json({
      ok: true,
      data: {
        ref: "mock-evidence-tampered",
        kind: "specialist_output",
        correlation_id: "01JBQXMOCK0000000000000011",
        feature_id: "F6",
        body: { verdict: "CONFIRM" },
        sha256: "mock-evidence-tampered",
        verified: false,
      },
    }),
  ),

  http.get(`${BACKEND_ORIGIN}/evidence/:ref`, ({ params }) =>
    HttpResponse.json(
      {
        ok: false,
        error: { code: "EVIDENCE_NOT_FOUND", message: `no evidence ${String(params.ref)}`, correlation_id: "mock" },
      },
      { status: 404 },
    ),
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

  // Fixtures for the operations dashboard (frontend phase-04).
  http.get(`${BACKEND_ORIGIN}/operations/health`, () =>
    HttpResponse.json({
      ok: true,
      data: {
        breakers: [
          { breaker_name: "bedrock", state: "closed" },
          { breaker_name: "athena", state: "closed" },
          { breaker_name: "platform", state: "closed" },
        ],
        dlqs: [
          {
            queue_url: "https://sqs.us-east-1.amazonaws.com/111122223333/SessionKillDlq",
            approximate_messages: 0,
          },
        ],
      },
    }),
  ),

  http.get(`${BACKEND_ORIGIN}/operations/cost/weekly`, () =>
    HttpResponse.json({
      ok: true,
      data: {
        report_key: "SentinelReports/cost/2026-W30.json",
        body: { by_service: { bedrock: 42.1, athena: 5.3, lambda: 1.2 }, previous_week_usd: 40 },
      },
    }),
  ),

  // `/operations/dashboards/:name/share-url` (frontend phase-04 §4) has no
  // backend route yet -- 404 in local dev too, so `DeepTelemetryTab`'s
  // "not available yet" state is what developers see, not a silent mock
  // that would mask the real gap.
  http.get(`${BACKEND_ORIGIN}/operations/dashboards/:name/share-url`, () =>
    HttpResponse.json(
      { ok: false, error: { code: "NOT_FOUND", message: "not implemented", correlation_id: "mock" } },
      { status: 404 },
    ),
  ),

  // `/reports/weekly/:kind` (frontend phase-04 §5) -- only `cost` has a
  // fixture; the other three kinds 404 so the Reports page's "not
  // published yet" empty state has something to exercise locally.
  http.get(`${BACKEND_ORIGIN}/reports/weekly/cost`, () =>
    HttpResponse.json({
      ok: true,
      data: {
        retrieved_from_s3_key: "SentinelReports/cost/2026-W30.json",
        body: { by_service: { bedrock: 42.1, athena: 5.3, lambda: 1.2 }, previous_week_usd: 40 },
      },
    }),
  ),

  http.get(`${BACKEND_ORIGIN}/reports/weekly/:kind`, () =>
    HttpResponse.json(
      { ok: false, error: { code: "REPORT_NOT_FOUND", message: "no report published yet", correlation_id: "mock" } },
      { status: 404 },
    ),
  ),
];
