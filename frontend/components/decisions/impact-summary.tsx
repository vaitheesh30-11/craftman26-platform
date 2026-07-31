import type { FindingOut } from "@/lib/api-types";
import { PolicyPrettyPrint } from "@/components/findings/policy-pretty-print";

/**
 * Phase-03 §3 step 3: reads the linked Finding's payload, with a
 * feature-specific summary for F4/F5/F7/F8 and an honest generic
 * pretty-print fallback for everything else -- same posture
 * `finding-detail.tsx#FeaturePayload` already takes for F2-F8, since none
 * of those payload shapes are finalized contracts in this codebase yet.
 */
export function ImpactSummary({ finding }: { finding: FindingOut | null }) {
  if (!finding) {
    return (
      <p className="text-sm text-muted-foreground">
        No linked Finding is available for this remediation -- impact cannot be previewed.
      </p>
    );
  }

  const payload = finding.payload;

  if (finding.feature_id === "F4") {
    const blockedRoles = payload["blocked_roles"];
    if (Array.isArray(blockedRoles) && blockedRoles.length > 0) {
      return (
        <div>
          <p className="text-sm font-semibold">Blocked-role summary</p>
          <ul className="ml-4 mt-1 list-disc space-y-1 text-sm">
            {blockedRoles.map((role, index) => (
              <li key={index}>{typeof role === "string" ? role : JSON.stringify(role)}</li>
            ))}
          </ul>
        </div>
      );
    }
  }

  if (finding.feature_id === "F5") {
    const terminations = payload["termination_records"] ?? payload["terminations"];
    if (Array.isArray(terminations) && terminations.length > 0) {
      return (
        <div>
          <p className="text-sm font-semibold">Termination records</p>
          <ul className="ml-4 mt-1 list-disc space-y-1 text-sm">
            {terminations.map((record, index) => (
              <li key={index}>{typeof record === "string" ? record : JSON.stringify(record)}</li>
            ))}
          </ul>
        </div>
      );
    }
  }

  if (finding.feature_id === "F7") {
    const collision = payload["collision_explanation"] ?? payload["collision"];
    if (typeof collision === "string") {
      return (
        <div>
          <p className="text-sm font-semibold">Collision explanation</p>
          <p className="mt-1 whitespace-pre-wrap text-sm">{collision}</p>
        </div>
      );
    }
  }

  if (finding.feature_id === "F8") {
    const safeScp = payload["safe_scp"] ?? payload["safe_scp_diff"];
    if (safeScp !== undefined) {
      return <PolicyPrettyPrint document={safeScp} label="safe_scp diff" />;
    }
  }

  if (Object.keys(payload).length === 0) {
    return <p className="text-sm text-muted-foreground">No impact payload attached to the linked finding.</p>;
  }

  return <PolicyPrettyPrint document={payload} label={`${finding.feature_id} payload`} />;
}
