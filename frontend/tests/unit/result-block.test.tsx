import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ResultBlock } from "@/components/chat/result-block";
import type { DecisionOut } from "@/lib/api-types";

// Canonical DecisionRecord fixture (docs/DATA_CONTRACTS.md §7), mirroring
// the shape `event: result` delivers off the wire.
const DECISION: DecisionOut = {
  decision_id: "01JBQXFIXTURE0000000000001",
  correlation_id: "01JBQXFIXTURE0000000000002",
  principal: "arn:aws:iam::111122223333:user/dev",
  query: {},
  specialist_verdicts: [],
  findings: [
    {
      finding_id: "01JBQXFIXTURE0000000000003",
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
      payload: {},
      detected_at: "2026-07-31T00:00:00Z",
      expires_at: null,
      evidence_ref: null,
      status: "OPEN",
    },
  ],
  remediations_proposed: [{ action: "attach_inline_policy", target_arn: "arn:aws:iam::111122223333:role/example-role" }],
  remediations_applied: [],
  status: "ESCALATED",
  narrative: "example-role's wildcard PassRole grant reaches an admin-equivalent role.",
  evidence_ref: {},
  decided_at: "2026-07-31T00:00:00Z",
};

describe("ResultBlock", () => {
  it("renders status, narrative, findings, and remediations from a DecisionRecord fixture", () => {
    render(<ResultBlock decision={DECISION} />);

    // `getByText`/`getByRole` already throw if nothing matches.
    screen.getByText("ESCALATED");
    screen.getByText(/wildcard PassRole grant reaches/);
    screen.getByText("Wildcard PassRole grant reaches an admin-equivalent role");
    screen.getByText("attach_inline_policy");
    expect(screen.getByRole("link", { name: "Approve" }).getAttribute("href")).toBe(
      `/decisions/${DECISION.decision_id}`,
    );
  });
});
