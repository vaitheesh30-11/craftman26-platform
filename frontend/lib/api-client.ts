/**
 * Typed client over the BFF proxy (`app/api/proxy/[...path]/route.ts`).
 * Every call is same-origin (`/api/proxy/...`) — the browser never learns
 * `BACKEND_ORIGIN` or holds a bearer token (phase-00 §3/§4).
 */
import type {
  ApiEnvelope,
  ApprovalRequest,
  ApprovalResponse,
  ChatRequest,
  CostReportOut,
  DashboardShareUrlOut,
  DecisionOut,
  DecisionsPage,
  EvidenceOut,
  ExecutionStatusOut,
  FaultsPage,
  FindingOut,
  FindingsPage,
  HealthResponse,
  HealthSnapshotOut,
  ReportOut,
} from "@/lib/api-types";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly code: string,
    readonly status: number,
    readonly correlationId: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function csrfHeaderIfNeeded(method: string): Record<string, string> {
  if (method === "GET" || method === "HEAD" || typeof document === "undefined") {
    return {};
  }
  const match = document.cookie.match(/(?:^|; )sentinel_csrf=([^;]+)/);
  return match?.[1] ? { "x-csrf-token": decodeURIComponent(match[1]) } : {};
}

async function request<T>(
  path: string,
  init: { method?: string; body?: unknown; searchParams?: Record<string, string | undefined> } = {},
): Promise<T> {
  const method = init.method ?? "GET";
  const url = new URL(`/api/proxy${path}`, typeof window === "undefined" ? "http://localhost" : window.location.origin);
  for (const [key, value] of Object.entries(init.searchParams ?? {})) {
    if (value !== undefined) url.searchParams.set(key, value);
  }

  const response = await fetch(url.pathname + url.search, {
    method,
    headers: {
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...csrfHeaderIfNeeded(method),
    },
    body: init.body ? JSON.stringify(init.body) : undefined,
    credentials: "same-origin",
  });

  const envelope = (await response.json()) as ApiEnvelope<T>;
  if (!envelope.ok) {
    throw new ApiError(envelope.error.message, envelope.error.code, response.status, envelope.error.correlation_id);
  }
  return envelope.data;
}

export const apiClient = {
  health: (): Promise<HealthResponse> => request("/health"),

  listFindings: (params: {
    severity?: string;
    feature_id?: string;
    account_id?: string;
    principal_arn?: string;
    since?: string;
    limit?: number;
    next_token?: string;
  }): Promise<FindingsPage> =>
    request("/findings", {
      searchParams: {
        severity: params.severity,
        feature_id: params.feature_id,
        account_id: params.account_id,
        principal_arn: params.principal_arn,
        since: params.since,
        limit: params.limit?.toString(),
        next_token: params.next_token,
      },
    }),

  getFinding: (findingId: string): Promise<FindingOut> => request(`/findings/${encodeURIComponent(findingId)}`),

  // `/evidence/{ref}` (backend phase-04) is being built in parallel and may
  // 404/502 until that branch merges -- callers (EvidenceViewer) must treat
  // any rejection as "not verifiable yet," not a crash.
  getEvidence: (ref: string): Promise<EvidenceOut> => request(`/evidence/${encodeURIComponent(ref)}`),

  listDecisions: (params: { next_token?: string; limit?: number } = {}): Promise<DecisionsPage> =>
    request("/decisions", {
      searchParams: { next_token: params.next_token, limit: params.limit?.toString() },
    }),

  getDecision: (decisionId: string): Promise<DecisionOut> => request(`/decisions/${encodeURIComponent(decisionId)}`),

  approveDecision: (decisionId: string, body: ApprovalRequest): Promise<ApprovalResponse> =>
    request(`/decisions/${encodeURIComponent(decisionId)}/approve`, { method: "POST", body }),

  rejectDecision: (decisionId: string, body: ApprovalRequest): Promise<ApprovalResponse> =>
    request(`/decisions/${encodeURIComponent(decisionId)}/reject`, { method: "POST", body }),

  askPrime: (body: ChatRequest): Promise<DecisionOut> => request("/agent/chat", { method: "POST", body }),

  listFaults: (params: { next_token?: string; limit?: number } = {}): Promise<FaultsPage> =>
    request("/operations/faults", {
      searchParams: { next_token: params.next_token, limit: params.limit?.toString() },
    }),

  latestCostReport: (): Promise<CostReportOut> => request("/operations/cost/weekly"),

  getOperationsHealth: (): Promise<HealthSnapshotOut> => request("/operations/health"),

  latestWeeklyReport: (reportKind: string): Promise<ReportOut> =>
    request(`/reports/weekly/${encodeURIComponent(reportKind)}`),

  getReportByKey: (key: string): Promise<ReportOut> => request(`/reports/${key}`),

  // `/operations/dashboards/{name}/share-url` (frontend phase-04 §4) has no
  // backend route yet -- see `DashboardShareUrlOut`'s doc comment. Wired up
  // now so `DeepTelemetryTab` only needs its `ApiError` catch path deleted
  // once the real endpoint ships, same precedent as `getEvidence` above.
  getDashboardShareUrl: (name: string): Promise<DashboardShareUrlOut> =>
    request(`/operations/dashboards/${encodeURIComponent(name)}/share-url`),

  // `GET /operations/execution/{arn}` doesn't exist on `backend` yet (see
  // `lib/api-types.ts`'s `ExecutionStatusOut` doc comment) -- callers
  // (`ApprovalProgress`) must treat any rejection the same way
  // `EvidenceViewer` treats a missing `/evidence/{ref}`: a graceful
  // "not available" state, never a crash.
  getExecutionStatus: (executionArn: string): Promise<ExecutionStatusOut> =>
    request(`/operations/execution/${encodeURIComponent(executionArn)}`),
};
