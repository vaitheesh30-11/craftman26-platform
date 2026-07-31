import { render, screen } from "@testing-library/react";
import { describe, it } from "vitest";

import { SeverityBadge } from "@/components/findings/severity-badge";
import type { Severity } from "@/lib/api-types";

describe("SeverityBadge", () => {
  it.each<Severity>(["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"])("renders the %s label", (severity) => {
    render(<SeverityBadge severity={severity} />);
    screen.getByText(severity);
  });
});
