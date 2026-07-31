import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, it, vi } from "vitest";

import type { FaultsPage, HealthSnapshotOut } from "@/lib/api-types";

const getOperationsHealth = vi.fn<() => Promise<HealthSnapshotOut>>();
const listFaults = vi.fn<() => Promise<FaultsPage>>();

vi.mock("@/lib/api-client", () => ({
  apiClient: { getOperationsHealth: () => getOperationsHealth(), listFaults: () => listFaults() },
  ApiError: class ApiError extends Error {},
}));

const { HealthTile } = await import("@/components/operations/health-tile");

function renderWithQueryClient(children: React.ReactElement) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>{children}</QueryClientProvider>);
}

describe("HealthTile", () => {
  it("renders breaker states, DLQ depth, and faults-by-class from fixture data", async () => {
    getOperationsHealth.mockResolvedValueOnce({
      breakers: [
        { breaker_name: "bedrock", state: "closed" },
        { breaker_name: "athena", state: "open" },
      ],
      dlqs: [{ queue_url: "https://sqs.us-east-1.amazonaws.com/123456789012/SessionKillDlq", approximate_messages: 3 }],
    });
    listFaults.mockResolvedValueOnce({
      items: [
        {
          correlation_id: "c1",
          fault_class: "transient_throttling",
          origin: "o",
          action_taken: "retried",
          detail: "d",
          detected_at: new Date().toISOString(),
          resolved_at: null,
        },
      ],
      next_token: null,
    });

    renderWithQueryClient(<HealthTile />);

    await screen.findByText("bedrock: closed");
    screen.getByText("athena: open");
    screen.getByText("SessionKillDlq");
    screen.getByText("3");
    screen.getByText("transient_throttling: 1");
  });
});
