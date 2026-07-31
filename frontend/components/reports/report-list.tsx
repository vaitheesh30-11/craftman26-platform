"use client";

import type { Route } from "next";
import { useRouter, useSearchParams } from "next/navigation";

import { REPORT_KINDS } from "@/lib/report-kinds";
import { Badge } from "@/components/ui/badge";

/**
 * Report-kind selector (phase-04 §5 "Filter by kind"). URL-synced like
 * `FindingsFilters` (phase-02) so a specific report kind is deep-linkable.
 */
export function ReportList() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const selectedKind = searchParams.get("kind") ?? REPORT_KINDS[0]?.kind;

  function selectKind(kind: string) {
    const next = new URLSearchParams(searchParams.toString());
    next.set("kind", kind);
    router.push(`/reports?${next.toString()}` as Route);
  }

  return (
    <div role="group" aria-label="Report kinds" className="flex flex-wrap gap-1.5">
      {REPORT_KINDS.map(({ kind, label, featureId }) => (
        <button key={kind} type="button" aria-pressed={selectedKind === kind} onClick={() => selectKind(kind)}>
          <Badge variant={selectedKind === kind ? "default" : "outline"}>
            {label}
            {featureId ? ` (${featureId})` : ""}
          </Badge>
        </button>
      ))}
    </div>
  );
}
