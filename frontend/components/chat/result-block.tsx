import type { DecisionOut } from "@/lib/api-types";
import { Badge, type BadgeProps } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { FindingChip } from "@/components/chat/finding-chip";

const STATUS_VARIANT: Record<DecisionOut["status"], BadgeProps["variant"]> = {
  ANSWERED: "default",
  AUTO_REMEDIATED: "default",
  ESCALATED: "medium",
  REJECTED: "destructive",
};

/**
 * Renders the terminal `event: result` payload (a raw `DecisionRecord`
 * dict off the wire) once it swaps in for a turn's progress placeholder
 * (phase-01 §4). Cast at the call site, not validated here -- same
 * boundary posture as ADR 0021's hand-mirrored response types.
 */
export function ResultBlock({ decision }: { decision: DecisionOut }) {
  return (
    <section className="space-y-4 rounded-lg border bg-card p-4" aria-label="Sentinel Prime result">
      <div className="flex items-center gap-2">
        <Badge variant={STATUS_VARIANT[decision.status]}>{decision.status}</Badge>
        <span className="text-xs text-muted-foreground">{decision.decision_id}</span>
      </div>

      <p className="text-sm">{decision.narrative}</p>

      {decision.findings.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold">Findings</h3>
          <ul className="mt-2 space-y-2">
            {decision.findings.map((finding) => (
              <FindingChip key={finding.finding_id} finding={finding} />
            ))}
          </ul>
        </div>
      )}

      {decision.remediations_proposed.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold">Proposed remediations</h3>
          <ul className="mt-2 space-y-2">
            {decision.remediations_proposed.map((remediation, index) => (
              <li key={index} className="flex items-center justify-between rounded-md border p-3">
                <span className="text-sm">{String(remediation["action"] ?? "remediation")}</span>
                {/* `/decisions/[id]` (approval flow, phase-03) doesn't exist yet --
                    plain `<a>` sidesteps typedRoutes' compile-time check on a page
                    that isn't built. */}
                <Button asChild size="sm" variant="outline">
                  <a href={`/decisions/${encodeURIComponent(decision.decision_id)}`}>Approve</a>
                </Button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
