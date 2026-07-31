import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { FindingOut, FindingsPage } from "@/lib/api-types";

const listFindings = vi.fn<() => Promise<FindingsPage>>();
vi.mock("@/lib/api-client", () => ({
  apiClient: { listFindings: () => listFindings() },
  ApiError: class ApiError extends Error {},
}));

const { RevocationsTile } = await import("@/components/operations/revocations-tile");

function makeF5Finding(): FindingOut {
  return {
    finding_id: "01JBQXFIXTURE",
    feature_id: "F5",
    account_id: "111122223333",
    principal_arn: "arn:aws:iam::111122223333:role/example-role",
    resource_arn: null,
    severity: "HIGH",
    title: "fixture",
    detail: "fixture",
    aws_doc_citation: {
      gap_id: "F5",
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

describe("RevocationsTile", () => {
  it("counts F5 findings and deep-links to the F5 findings view", async () => {
    listFindings.mockResolvedValueOnce({ items: [makeF5Finding(), makeF5Finding()], next_token: null });

    renderWithQueryClient(<RevocationsTile />);

    await screen.findByText("2");
    expect(screen.getByRole("link", { name: "Emergency revocations" }).getAttribute("href")).toBe(
      "/findings?feature=F5",
    );
  });
});
