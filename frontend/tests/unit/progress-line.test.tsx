import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ProgressLine } from "@/components/chat/progress-line";

describe("ProgressLine", () => {
  it("renders the given text with an animated ellipsis", () => {
    render(<ProgressLine text="Sentinel Prime is thinking" />);
    // `getByText`/`getAllByText` already throw if nothing matches, so a
    // successful call is itself the presence assertion.
    screen.getByText("Sentinel Prime is thinking");
    expect(screen.getAllByText(".")).toHaveLength(3);
  });
});
