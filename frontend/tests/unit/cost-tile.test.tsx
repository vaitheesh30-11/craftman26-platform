import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, it, vi } from "vitest";

import type { CostReportOut } from "@/lib/api-types";

const latestCostReport = vi.fn<() => Promise<CostReportOut>>();

class FakeApiError extends Error {
  constructor(message: string, readonly code: string, readonly status: number) {
    super(message);
  }
}

vi.mock("@/lib/api-client", () => ({
  apiClient: { latestCostReport: () => latestCostReport() },
  ApiError: FakeApiError,
}));

const { CostTile } = await import("@/components/operations/cost-tile");

function renderWithQueryClient(children: React.ReactElement) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>{children}</QueryClientProvider>);
}

describe("CostTile", () => {
  it("renders total and per-service figures from a fixture cost report", async () => {
    latestCostReport.mockResolvedValueOnce({
      report_key: "SentinelReports/cost/2026-W30.json",
      body: { by_service: { bedrock: 12.5, athena: 3.25, lambda: 0.75 }, previous_week_usd: 10 },
    });

    renderWithQueryClient(<CostTile />);

    await screen.findByText("$16.50");
    screen.getByText("$12.50");
    screen.getByText("$3.25");
    screen.getByText("$0.75");
  });

  it("shows a not-published empty state on a 404", async () => {
    latestCostReport.mockRejectedValueOnce(new FakeApiError("not found", "COST_REPORT_NOT_FOUND", 404));

    renderWithQueryClient(<CostTile />);

    await screen.findByText("No cost report published yet.");
  });
});
