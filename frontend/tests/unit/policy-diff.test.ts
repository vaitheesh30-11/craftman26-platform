import { describe, expect, it } from "vitest";

import { diffHasChanges, diffPolicies } from "@/lib/policy-diff";

describe("diffPolicies", () => {
  it("marks identical documents as fully unchanged", () => {
    const doc = { Version: "2012-10-17", Statement: [] };
    const diff = diffPolicies(doc, doc);
    expect(diffHasChanges(diff)).toBe(false);
    expect(diff.every((line) => line.kind === "unchanged")).toBe(true);
  });

  it("reports an added and a removed line for a single-field change", () => {
    const current = { Effect: "Allow" };
    const proposed = { Effect: "Deny" };
    const diff = diffPolicies(current, proposed);
    expect(diffHasChanges(diff)).toBe(true);
    expect(diff.some((l) => l.kind === "removed" && l.value.includes("Allow"))).toBe(true);
    expect(diff.some((l) => l.kind === "added" && l.value.includes("Deny"))).toBe(true);
  });

  it("handles a ~6KB policy document without throwing (phase-03 §7)", () => {
    const bigStatement = Array.from({ length: 120 }, (_, i) => ({
      Effect: "Allow",
      Action: `service${i}:Action${i}`,
      Resource: "*",
    }));
    const current = { Version: "2012-10-17", Statement: bigStatement };
    const proposed = { Version: "2012-10-17", Statement: [...bigStatement, { Effect: "Deny", Action: "*", Resource: "*" }] };
    expect(() => diffPolicies(current, proposed)).not.toThrow();
    const json = JSON.stringify(proposed);
    expect(new TextEncoder().encode(json).length).toBeGreaterThan(4000);
  });
});
