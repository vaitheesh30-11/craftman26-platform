"use client";

import { useState } from "react";

import type { FindingOut } from "@/lib/api-types";
import { Badge, type BadgeProps } from "@/components/ui/badge";
import { CitationInline } from "@/components/chat/citation-inline";

const SEVERITY_VARIANT: Record<FindingOut["severity"], BadgeProps["variant"]> = {
  INFO: "info",
  LOW: "low",
  MEDIUM: "medium",
  HIGH: "high",
  CRITICAL: "critical",
};

// `/findings/[id]` (phase-02, Findings Inbox) doesn't exist yet -- a plain
// `<a>` rather than `next/link` deliberately sidesteps `typedRoutes`'s
// compile-time route check, which would otherwise reject a href to a page
// that isn't built yet. The href shape itself is still the real contract
// phase-02 will serve.
export function FindingChip({ finding }: { finding: FindingOut }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <li className="rounded-md border p-3">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        className="flex w-full items-center justify-between gap-2 text-left"
      >
        <span className="flex items-center gap-2">
          <Badge variant={SEVERITY_VARIANT[finding.severity]}>{finding.severity}</Badge>
          <span className="text-sm font-medium">{finding.title}</span>
        </span>
        <a
          href={`/findings/${encodeURIComponent(finding.finding_id)}`}
          onClick={(e) => e.stopPropagation()}
          className="text-xs text-muted-foreground underline hover:text-foreground"
        >
          {finding.finding_id}
        </a>
      </button>
      {expanded && (
        <div className="mt-2">
          <p className="text-sm">{finding.detail}</p>
          <CitationInline citation={finding.aws_doc_citation} />
        </div>
      )}
    </li>
  );
}
