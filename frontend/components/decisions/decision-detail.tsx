"use client";

import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/lib/api-client";
import type { CallerPersona } from "@/lib/principal";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { RemediationCard } from "@/components/decisions/remediation-card";

/**
 * Phase-03 §3 step 1: "each remediation in `remediations_proposed` renders
 * as a RemediationCard." A remediation's linked Finding is matched
 * best-effort by `finding_id` if the remediation dict carries one --
 * `DecisionOut.remediations_proposed` has no documented FK to
 * `DecisionOut.findings` (`docs/DATA_CONTRACTS.md` §7 doesn't name one
 * either), so falling back to "no linked finding" for `ImpactSummary` is
 * the honest behavior when that field is absent, same posture as
 * `finding-detail.tsx`'s "Related" section.
 */
export function DecisionDetail({ decisionId, persona }: { decisionId: string; persona: CallerPersona | null }) {
  const { data, isPending, isError } = useQuery({
    queryKey: ["decision", decisionId],
    queryFn: () => apiClient.getDecision(decisionId),
  });

  if (isPending) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-8 w-1/2" />
        <Skeleton className="h-32 w-full" />
      </div>
    );
  }

  if (isError || !data) {
    return <p className="text-sm text-destructive">Failed to load this decision.</p>;
  }

  return (
    <article className="space-y-6">
      <header className="space-y-2">
        <div className="flex items-center gap-2">
          <Badge variant="outline">{data.status}</Badge>
          <span className="text-xs text-muted-foreground">{new Date(data.decided_at).toLocaleString()}</span>
        </div>
        <h1 className="text-xl font-semibold tracking-tight">Decision {data.decision_id}</h1>
        <p className="whitespace-pre-wrap text-sm text-muted-foreground">{data.narrative}</p>
      </header>

      <section aria-label="Proposed remediations" className="space-y-3">
        <h2 className="text-sm font-semibold">Proposed remediations</h2>
        {data.remediations_proposed.length === 0 ? (
          <p className="text-sm text-muted-foreground">This decision has no proposed remediations.</p>
        ) : (
          <div className="space-y-3">
            {data.remediations_proposed.map((remediation, index) => {
              const findingId = remediation["finding_id"];
              const linkedFinding =
                typeof findingId === "string" ? data.findings.find((f) => f.finding_id === findingId) ?? null : null;
              return (
                <RemediationCard
                  key={index}
                  decisionId={decisionId}
                  remediationIndex={index}
                  remediation={remediation}
                  finding={linkedFinding}
                  severity={linkedFinding?.severity ?? null}
                  persona={persona}
                />
              );
            })}
          </div>
        )}
      </section>
    </article>
  );
}
