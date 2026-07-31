import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FindingDetail } from "@/components/findings/finding-detail";
import type { FindingOut } from "@/lib/api-types";

const FINDING: FindingOut = {
  finding_id: "01JBQXFIXTURE0000000000010",
  feature_id: "F1",
  account_id: "111122223333",
  principal_arn: "arn:aws:iam::111122223333:role/example-role",
  resource_arn: null,
  severity: "CRITICAL",
  title: "Wildcard PassRole grant reaches an admin-equivalent role",
  detail: "example-role can PassRole into blast-radius CRITICAL targets.",
  aws_doc_citation: {
    gap_id: "F1",
    quote: "You must grant iam:PassRole for the specific roles you want to allow.",
    source: "IAM User Guide",
    url: "https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_use_passrole.html",
    retrieved_on: "2026-07-01",
  },
  payload: { blast_path: ["role/example-role", "role/OrganizationAccountAccessRole"] },
  detected_at: "2026-07-31T00:00:00Z",
  expires_at: null,
  evidence_ref: null, // exercises EvidenceViewer's "missing" state without a network call
  status: "OPEN",
};

function renderWithQueryClient(children: React.ReactElement) {
  const queryClient = new QueryClient();
  return render(<QueryClientProvider client={queryClient}>{children}</QueryClientProvider>);
}

describe("FindingDetail", () => {
  // Both assertions share a single render -- this file's `vitest.config.ts`
  // doesn't enable Vitest's `globals` mode, so `@testing-library/react`'s
  // auto-cleanup-on-`afterEach` never registers and a second `render()` in
  // the same file would leave the first render's DOM behind, causing
  // `getByText` to see duplicates.
  it("renders the citation prominently and the F1 blast path", () => {
    renderWithQueryClient(<FindingDetail finding={FINDING} />);

    const callout = screen.getByRole("region", { name: "AWS documentation citation" });
    expect(callout.textContent).toContain(FINDING.aws_doc_citation.quote);
    expect(callout.textContent).toContain(FINDING.aws_doc_citation.source);

    screen.getByText("role/example-role");
    screen.getByText("role/OrganizationAccountAccessRole");
    screen.getByText("No evidence recorded");
  });
});
