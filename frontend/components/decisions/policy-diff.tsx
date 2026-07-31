"use client";

import { useMemo, useState } from "react";

import { diffPolicies, type DiffLine } from "@/lib/policy-diff";
import { Button } from "@/components/ui/button";

function lineClass(kind: DiffLine["kind"]): string {
  if (kind === "added") return "bg-severity-low/15 text-foreground";
  if (kind === "removed") return "bg-severity-critical/15 text-foreground";
  return "";
}

function UnifiedView({ diff }: { diff: DiffLine[] }) {
  return (
    <pre className="max-h-96 overflow-auto rounded-md bg-muted/30 p-3 text-xs" aria-label="Unified policy diff">
      <code>
        {diff.map((line, index) => (
          <div key={index} className={lineClass(line.kind)}>
            {line.kind === "added" ? "+ " : line.kind === "removed" ? "- " : "  "}
            {line.value}
          </div>
        ))}
      </code>
    </pre>
  );
}

function SideBySideView({ diff }: { diff: DiffLine[] }) {
  return (
    <div className="grid max-h-96 grid-cols-2 gap-px overflow-auto rounded-md border text-xs">
      <div aria-label="Current policy" className="bg-muted/30 p-3">
        <p className="mb-1 font-semibold text-muted-foreground">Current</p>
        <pre>
          <code>
            {diff
              .filter((line) => line.kind !== "added")
              .map((line, index) => (
                <div key={index} className={lineClass(line.kind === "removed" ? "removed" : "unchanged")}>
                  {line.value}
                </div>
              ))}
          </code>
        </pre>
      </div>
      <div aria-label="Proposed policy" className="bg-muted/30 p-3">
        <p className="mb-1 font-semibold text-muted-foreground">Proposed</p>
        <pre>
          <code>
            {diff
              .filter((line) => line.kind !== "removed")
              .map((line, index) => (
                <div key={index} className={lineClass(line.kind === "added" ? "added" : "unchanged")}>
                  {line.value}
                </div>
              ))}
          </code>
        </pre>
      </div>
    </div>
  );
}

/**
 * Phase-03 §3 step 1: "Side-by-side JSON diff of current vs proposed
 * policy. Toggle to view unified diff." Diffs client-side (see
 * `lib/policy-diff.ts`'s doc comment on why -- no
 * `/decisions/{id}/diff/{remediation_index}` endpoint exists yet, §8's
 * risk note flags that as a future backend phase-04 offer).
 */
export function PolicyDiff({ current, proposed }: { current: unknown; proposed: unknown }) {
  const [mode, setMode] = useState<"side-by-side" | "unified">("side-by-side");
  const diff = useMemo(() => diffPolicies(current ?? {}, proposed ?? {}), [current, proposed]);

  if (current === null && proposed === null) {
    return (
      <p className="text-sm text-muted-foreground">
        This remediation carries no `current_policy`/`proposed_policy` fields to diff.
      </p>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex justify-end gap-1">
        <Button
          type="button"
          size="sm"
          variant={mode === "side-by-side" ? "default" : "outline"}
          onClick={() => setMode("side-by-side")}
        >
          Side-by-side
        </Button>
        <Button
          type="button"
          size="sm"
          variant={mode === "unified" ? "default" : "outline"}
          onClick={() => setMode("unified")}
        >
          Unified
        </Button>
      </div>
      {mode === "side-by-side" ? <SideBySideView diff={diff} /> : <UnifiedView diff={diff} />}
    </div>
  );
}
