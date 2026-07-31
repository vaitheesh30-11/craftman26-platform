import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { FindingOut, FindingsPage } from "@/lib/api-types";

const listFindings = vi.fn<() => Promise<FindingsPage>>();
vi.mock("@/lib/api-client", () => ({
  apiClient: { listFindings: (...args: unknown[]) => listFindings(...(args as [])) },
  ApiError: class ApiError extends Error {},
}));

const { FindingsTile } = await import("@/components/operations/findings-tile");

function makeFinding(overrides: Partial<FindingOut>): FindingOut {
  return {
    finding_id: "01JBQXFIXTURE",
    feature_id: "F1",
    account_id: "111122223333",
    principal_arn: "arn:aws:iam::111122223333:role/example-role",
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
    ...overrides,
  };
}

function renderWithQueryClient(children: React.ReactElement) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>{children}</QueryClientProvider>);
}

describe("FindingsTile", () => {
  it("shows the count of severity >= MEDIUM findings from fixture data", async () => {
    listFindings.mockResolvedValueOnce({
      items: [
        makeFinding({ severity: "INFO" }),
        makeFinding({ severity: "MEDIUM" }),
        makeFinding({ severity: "CRITICAL" }),
      ],
      next_token: null,
    });

    renderWithQueryClient(<FindingsTile />);

    await screen.findByText("2");
    expect(screen.getByRole("link", { name: "Findings" }).getAttribute("href")).toBe(
      "/findings?severity=CRITICAL,HIGH,MEDIUM&since=7d",
    );
  });
});
