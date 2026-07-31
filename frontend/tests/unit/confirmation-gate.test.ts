import { describe, expect, it } from "vitest";

import { isConfirmationValid, type ConfirmationValue } from "@/components/decisions/confirmation-box";

const EXPECTED = "example-role";

// Phase-03 §6: "Property: approve button cannot enable when confirmation
// gates fail (10 fixture combinations)." Each row below is one gate
// combination -- typed target correct/incorrect/empty, reviewed true/false,
// reason empty/too-short/valid -- and its expected validity.
const FIXTURES: { name: string; value: ConfirmationValue; valid: boolean }[] = [
  { name: "all valid, empty reason", value: { typedTarget: EXPECTED, reviewed: true, reason: "" }, valid: true },
  {
    name: "all valid, long reason",
    value: { typedTarget: EXPECTED, reviewed: true, reason: "a".repeat(25) },
    valid: true,
  },
  { name: "typed target wrong", value: { typedTarget: "wrong-role", reviewed: true, reason: "" }, valid: false },
  { name: "typed target empty", value: { typedTarget: "", reviewed: true, reason: "" }, valid: false },
  { name: "not reviewed", value: { typedTarget: EXPECTED, reviewed: false, reason: "" }, valid: false },
  {
    name: "reason too short",
    value: { typedTarget: EXPECTED, reviewed: true, reason: "too short" },
    valid: false,
  },
  {
    name: "reason exactly 20 chars",
    value: { typedTarget: EXPECTED, reviewed: true, reason: "a".repeat(20) },
    valid: true,
  },
  {
    name: "reason 19 chars",
    value: { typedTarget: EXPECTED, reviewed: true, reason: "a".repeat(19) },
    valid: false,
  },
  {
    name: "typed target wrong and not reviewed",
    value: { typedTarget: "wrong-role", reviewed: false, reason: "" },
    valid: false,
  },
  {
    name: "everything fails",
    value: { typedTarget: "wrong-role", reviewed: false, reason: "short" },
    valid: false,
  },
];

describe("isConfirmationValid", () => {
  it.each(FIXTURES)("$name -> valid=$valid", ({ value, valid }) => {
    expect(isConfirmationValid(EXPECTED, value)).toBe(valid);
  });
});
