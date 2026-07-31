import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { FindingOut, FindingsPage } from "@/lib/api-types";

const listFindings = vi.fn<() => Promise<FindingsPage>>();
vi.mock("@/lib/api-client", () => ({
  apiClient: { listFindings: () => listFindings() },
  ApiError: class ApiError extends Error {},
}));

const { TopPrincipalsTile } = await import("@/components/operations/top-principals-tile");

function makeFinding(principalArn: string | null): FindingOut {
  return {
    finding_id: "01JBQXFIXTURE",
    feature_id: "F1",
    account_id: "111122223333",
    principal_arn: principalArn,
    resource_arn: null,
    severity: "HIGH",
    title: "fixture",
    detail: "fixture",
    aws_doc_citation: {
      gap_id: "F1",
      quote: "q",
      source: "s",
      url: "https://docs.aws.amazon.com/x",
      retrieved_on: "2026-07-01",
    },
    payload: {},
    detected_at: new Date().toISOString(),
    expires_at: null,
    evidence_ref: null,
    status: "OPEN",
  };
}

function renderWithQueryClient(children: React.ReactElement) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>{children}</QueryClientProvider>);
}

describe("TopPrincipalsTile", () => {
  it("ranks principals by finding count and links each to a filtered findings view", async () => {
    const heavy = "arn:aws:iam::111122223333:role/heavy-offender";
    listFindings.mockResolvedValueOnce({
      items: [makeFinding(heavy), makeFinding(heavy), makeFinding("arn:aws:iam::111122223333:role/other"), makeFinding(null)],
      next_token: null,
    });

    renderWithQueryClient(<TopPrincipalsTile />);

    const link = await screen.findByRole("link", { name: "heavy-offender" });
    expect(link.getAttribute("href")).toBe(`/findings?principal_arn=${encodeURIComponent(heavy)}`);
    screen.getByText("2");
  });
});
