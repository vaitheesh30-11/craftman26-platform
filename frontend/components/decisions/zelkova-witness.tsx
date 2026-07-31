import { Badge } from "@/components/ui/badge";
import { PolicyPrettyPrint } from "@/components/findings/policy-pretty-print";

/**
 * Phase-03 §3 step 2. `remediation.zelkova_check`/`zelkova_precheck` isn't
 * a finalized field on any producer contract in this repo yet (loosely
 * typed the same way `DecisionOut.remediations_proposed` is, see
 * `lib/remediation-format.ts`) -- when absent, this renders the exact copy
 * the spec asks for rather than a blank section.
 */
export function ZelkovaWitness({ zelkovaCheck }: { zelkovaCheck: Record<string, unknown> | null }) {
  if (!zelkovaCheck) {
    return (
      <div className="rounded-md border border-dashed p-3">
        <Badge variant="secondary">Not yet run</Badge>
        <p className="mt-2 text-sm text-muted-foreground">
          Sentinel will run Zelkova CheckNoNewAccess before applying — witness will appear here if the check fails.
        </p>
      </div>
    );
  }

  const passed = zelkovaCheck["passed"] !== false;

  return (
    <div className={`rounded-md border p-3 ${passed ? "" : "border-destructive"}`}>
      <Badge variant={passed ? "low" : "destructive"}>{passed ? "CheckNoNewAccess passed" : "CheckNoNewAccess FAILED"}</Badge>
      <div className="mt-2">
        <PolicyPrettyPrint document={zelkovaCheck} label="Zelkova witness" />
      </div>
    </div>
  );
}
