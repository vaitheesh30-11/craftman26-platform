// `remediations_proposed[i]` is a loosely-typed dict (`DecisionOut.
// remediations_proposed: Record<string, unknown>[]`, mirroring backend
// `schemas/decision.py`'s own documented reason for keeping it loose --
// the producer-side `RemediationPlan` contract is deep and this UI only
// displays it). These helpers read the fields phase-03's spec names
// (§3 step "action kind", "target ARN", "TTL if any") defensively.

export type RemediationRecord = Record<string, unknown>;

export type RemediationLifecycleState =
  | "proposed"
  | "approved"
  | "rejected"
  | "applying"
  | "applied"
  | "rolled-back";

const APPROVABLE_ACTIONS = new Set([
  "attach_inline_policy",
  "detach_inline_policy",
  "update_scp",
  "archive_finding",
  "enable_cloudtrail_data_events",
  "auto_generate_policy",
]);

export function remediationAction(remediation: RemediationRecord): string {
  const action = remediation["action"];
  return typeof action === "string" ? action : "unknown_action";
}

export function remediationTargetArn(remediation: RemediationRecord): string | null {
  const target = remediation["target_arn"] ?? remediation["arn"] ?? remediation["resource_arn"];
  return typeof target === "string" ? target : null;
}

export function remediationTtlSeconds(remediation: RemediationRecord): number | null {
  const ttl = remediation["ttl_seconds"] ?? remediation["ttl"];
  return typeof ttl === "number" ? ttl : null;
}

export function remediationCurrentPolicy(remediation: RemediationRecord): unknown {
  return remediation["current_policy"] ?? remediation["before"] ?? null;
}

export function remediationProposedPolicy(remediation: RemediationRecord): unknown {
  return remediation["proposed_policy"] ?? remediation["after"] ?? null;
}

export function remediationZelkovaCheck(remediation: RemediationRecord): Record<string, unknown> | null {
  const check = remediation["zelkova_check"] ?? remediation["zelkova_precheck"];
  return check && typeof check === "object" ? (check as Record<string, unknown>) : null;
}

/**
 * `session_kill` is not in backend's `_APPROVABLE_ACTIONS`
 * (`backend/src/iam_sentinel_backend/services/approval_service.py`) -- F5
 * emergency session termination ships through its own `/emergency/*`
 * two-signer flow (`auth/breakglass.py`), not this endpoint. Phase-03 §4
 * still asks the UI to show break-glass messaging if a decision ever
 * proposes one here, so this stays permissive (never assume it can't
 * happen) rather than hiding the card.
 */
export function isSessionKill(remediation: RemediationRecord): boolean {
  return remediationAction(remediation) === "session_kill";
}

export function isBackendApprovable(remediation: RemediationRecord): boolean {
  return APPROVABLE_ACTIONS.has(remediationAction(remediation));
}

/**
 * Confirmation-box target string (phase-03 §3 step 4: "types the target
 * ARN's short form, e.g. last segment of the role"). Mirrors
 * `lib/findings-format.ts#shortArn`'s ARN-segment rule so both features
 * agree on what "short form" means.
 */
export function shortTarget(arn: string | null): string {
  if (!arn) return "";
  const slashIndex = arn.lastIndexOf("/");
  if (slashIndex !== -1) return arn.slice(slashIndex + 1);
  const colonIndex = arn.lastIndexOf(":");
  return colonIndex !== -1 ? arn.slice(colonIndex + 1) : arn;
}
