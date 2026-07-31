import { describe, expect, it } from "vitest";

import { REPORT_KINDS } from "@/lib/report-kinds";

// Contract/snapshot test (phase-04 §7): report kinds are enumerated in this
// one file; any drift (a kind renamed/removed/added) shows up as a failing
// snapshot review, per the spec's explicit ask.
describe("REPORT_KINDS", () => {
  it("has at least 4 kinds (phase-04 §8 acceptance criterion)", () => {
    expect(REPORT_KINDS.length).toBeGreaterThanOrEqual(4);
  });

  it("matches the known snapshot", () => {
    expect(REPORT_KINDS).toMatchInlineSnapshot(`
      [
        {
          "featureId": null,
          "kind": "cost",
          "label": "Weekly cost",
        },
        {
          "featureId": "F2",
          "kind": "f2_suppression",
          "label": "F2 suppression",
        },
        {
          "featureId": "F6",
          "kind": "f6_shadow",
          "label": "F6 shadow-SCP",
        },
        {
          "featureId": "F8",
          "kind": "f8_slr",
          "label": "F8 SLR breakage",
        },
      ]
    `);
  });

  it("has no duplicate kind strings", () => {
    const kinds = REPORT_KINDS.map((r) => r.kind);
    expect(new Set(kinds).size).toBe(kinds.length);
  });
});
