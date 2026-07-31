// Small formatting helpers shared by the findings inbox (table + detail).
// Kept free of React so they're trivially unit-testable and reusable from
// both server and client components.

const ACCOUNT_ID_PATTERN = /^\d{12}$/;

export function isValidAccountId(value: string): boolean {
  return ACCOUNT_ID_PATTERN.test(value);
}

// Display-only masking (phase-02 §9 risk mitigation): search/filtering
// always operates on the canonical 12-digit id, never the masked string.
export function maskAccountId(accountId: string, revealed: boolean): string {
  if (revealed || !ACCOUNT_ID_PATTERN.test(accountId)) return accountId;
  return `••••••••${accountId.slice(-4)}`;
}

// `principal_arn` / `resource_arn` short form: the last `/` or `:` segment,
// e.g. `arn:aws:iam::111122223333:role/example-role` -> `role/example-role`.
export function shortArn(arn: string | null): string {
  if (!arn) return "—";
  const slashIndex = arn.lastIndexOf("/");
  if (slashIndex !== -1) return arn.slice(slashIndex + 1);
  const colonIndex = arn.lastIndexOf(":");
  return colonIndex !== -1 ? arn.slice(colonIndex + 1) : arn;
}

const SEVERITY_RANK: Record<string, number> = {
  INFO: 0,
  LOW: 1,
  MEDIUM: 2,
  HIGH: 3,
  CRITICAL: 4,
};

export function severityRank(severity: string): number {
  return SEVERITY_RANK[severity] ?? -1;
}

export function formatRelativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return iso;
  const diffSeconds = Math.round((then - Date.now()) / 1000);
  const absSeconds = Math.abs(diffSeconds);

  const units: [Intl.RelativeTimeFormatUnit, number][] = [
    ["year", 31536000],
    ["month", 2592000],
    ["week", 604800],
    ["day", 86400],
    ["hour", 3600],
    ["minute", 60],
  ];
  for (const [unit, secondsInUnit] of units) {
    if (absSeconds >= secondsInUnit) {
      const value = Math.round(diffSeconds / secondsInUnit);
      return new Intl.RelativeTimeFormat("en", { numeric: "auto" }).format(value, unit);
    }
  }
  return new Intl.RelativeTimeFormat("en", { numeric: "auto" }).format(diffSeconds, "second");
}

const SINCE_WINDOW_MS: Record<string, number> = {
  "24h": 24 * 60 * 60 * 1000,
  "7d": 7 * 24 * 60 * 60 * 1000,
  "30d": 30 * 24 * 60 * 60 * 1000,
};

// Converts a filter-window token into the ISO timestamp `GET /findings`'s
// `since` param expects. `"custom"` is handled by the caller, which already
// has an explicit date string from the filter form.
export function sinceWindowToIso(window: string): string | undefined {
  const ms = SINCE_WINDOW_MS[window];
  return ms === undefined ? undefined : new Date(Date.now() - ms).toISOString();
}

// content-addressed evidence ref (DATA_CONTRACTS.md §6 `EvidenceRef.sha256`)
// is the only field on `Finding.evidence_ref` that's both stable and safe to
// put in a URL path segment (bucket/key can contain characters that need
// more careful escaping, and `key` is meant to be opaque to callers).
export function evidenceRefFromFinding(evidenceRef: Record<string, unknown> | null): string | null {
  if (!evidenceRef) return null;
  const sha256 = evidenceRef["sha256"];
  return typeof sha256 === "string" && sha256.length > 0 ? sha256 : null;
}
