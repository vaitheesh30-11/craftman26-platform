import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { RemediationCard } from "@/components/decisions/remediation-card";
import type { CallerPersona } from "@/lib/principal";
import type { RemediationRecord } from "@/lib/remediation-format";

const SCP_REMEDIATION: RemediationRecord = {
  action: "update_scp",
  target_arn: "arn:aws:organizations::111122223333:policy/o-example/service_control_policy/p-example",
  current_policy: { Version: "2012-10-17", Statement: [{ Effect: "Allow", Action: "*", Resource: "*" }] },
  proposed_policy: { Version: "2012-10-17", Statement: [{ Effect: "Deny", Action: "*", Resource: "*" }] },
};

const INLINE_REMEDIATION: RemediationRecord = {
  action: "attach_inline_policy",
  target_arn: "arn:aws:iam::111122223333:role/example-role",
  ttl_seconds: 3600,
};

function renderCard(remediation: RemediationRecord, persona: CallerPersona | null) {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <RemediationCard
        decisionId="dec-1"
        remediationIndex={0}
        remediation={remediation}
        finding={null}
        severity="HIGH"
        persona={persona}
      />
    </QueryClientProvider>,
  );
}

// This file's `vitest.config.ts` doesn't enable Vitest `globals` mode
// (same note as `tests/unit/finding-detail.test.tsx`), and no jest-dom
// matcher augmentation is picked up by `tsc --noEmit` here -- so
// assertions below use plain `screen.getBy*` (throws if absent) and DOM
// property reads instead of `toBeInTheDocument`/`toBeDisabled`.
describe("RemediationCard", () => {
  // Unlike `finding-detail.test.tsx` (one render shared across two
  // assertions), this file needs multiple independent renders per test --
  // `vitest.config.ts` doesn't enable globals-mode auto-cleanup, so it's
  // done explicitly here.
  afterEach(cleanup);

  it("renders the proposed state with action kind, target, and TTL", () => {
    renderCard(INLINE_REMEDIATION, null);
    screen.getByText("attach_inline_policy");
    screen.getByText("Proposed");
    screen.getByText("example-role");
    screen.getByText(/TTL 1h/);
  });

  it("gates SCP-update approval behind the SentinelOperators group (phase-03 §4)", async () => {
    const user = userEvent.setup();
    renderCard(SCP_REMEDIATION, { groups: [], email: null, isOperator: false, isBreakGlass: false });

    await user.click(screen.getByRole("button", { name: "Review" }));
    await user.click(screen.getByRole("button", { name: "Next" })); // diff -> zelkova
    await user.click(screen.getByRole("button", { name: "Next" })); // zelkova -> impact
    await user.click(screen.getByRole("button", { name: "Next" })); // impact -> confirm

    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain("Operator role required");

    const approveButton = screen.getByRole("button", { name: /Approve & apply/ }) as HTMLButtonElement;
    expect(approveButton.disabled).toBe(true);
  });

  it("does not gate a non-SCP action behind the operator group", async () => {
    const user = userEvent.setup();
    renderCard(INLINE_REMEDIATION, { groups: [], email: null, isOperator: false, isBreakGlass: false });

    await user.click(screen.getByRole("button", { name: "Review" }));
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.click(screen.getByRole("button", { name: "Next" }));

    expect(screen.queryByText("Operator role required")).toBe(null);
    // Still disabled -- confirmation fields haven't been filled in yet.
    const approveButton = screen.getByRole("button", { name: /Approve & apply/ }) as HTMLButtonElement;
    expect(approveButton.disabled).toBe(true);
  });
});
