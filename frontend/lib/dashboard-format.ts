// Pure helpers backing `components/operations/*-tile.tsx`. Kept free of
// React, same posture as `lib/findings-format.ts`, so each is trivially
// unit-testable with fixture data (frontend phase-04 §7 "Component: each
// tile with fixture data").
import type { FaultRecordOut, FindingOut, Severity } from "@/lib/api-types";
import { severityRank } from "@/lib/findings-format";

// Findings tile (phase-04 §3): "open findings (severity >= MEDIUM)".
export const AT_LEAST_MEDIUM: Severity[] = ["MEDIUM", "HIGH", "CRITICAL"];

export function isAtLeastMedium(severity: string): boolean {
  return severityRank(severity) >= severityRank("MEDIUM");
}

export function countAtLeastMedium(findings: FindingOut[]): number {
  return findings.filter((f) => isAtLeastMedium(f.severity)).length;
}

export interface SparklinePoint {
  date: string; // YYYY-MM-DD, UTC day bucket
  value: number;
}

/**
 * Severity-weighted daily sparkline (phase-04 §3 Findings Tile) over the
 * trailing `days` UTC day buckets, oldest first. Each finding contributes
 * its `severityRank` (0-4) to the bucket its `detected_at` falls in --
 * "severity-weighted" per the spec, not a plain count, so one CRITICAL
 * finding moves the line more than four INFO ones.
 */
export function severityWeightedSparkline(findings: FindingOut[], days = 7): SparklinePoint[] {
  const buckets = new Map<string, number>();
  const now = Date.now();
  for (let i = days - 1; i >= 0; i -= 1) {
    const day = new Date(now - i * 86_400_000).toISOString().slice(0, 10);
    buckets.set(day, 0);
  }
  for (const finding of findings) {
    const day = finding.detected_at.slice(0, 10);
    if (buckets.has(day)) {
      buckets.set(day, (buckets.get(day) ?? 0) + severityRank(finding.severity));
    }
  }
  return Array.from(buckets.entries()).map(([date, value]) => ({ date, value }));
}

export interface PrincipalCount {
  principal: string;
  count: number;
}

/** Top-N principals by finding count (phase-04 §3 Top Principals Tile). No
 * `/operations/top-principals` aggregate endpoint exists on the backend
 * (only `GET /findings`, which returns raw rows) -- this aggregates
 * client-side over whatever page of findings the caller already fetched.
 * Findings with no `principal_arn` (e.g. resource-only F3 findings) are
 * excluded; they have nothing to attribute to a principal.
 */
export function topPrincipals(findings: FindingOut[], limit = 5): PrincipalCount[] {
  const counts = new Map<string, number>();
  for (const finding of findings) {
    if (!finding.principal_arn) continue;
    counts.set(finding.principal_arn, (counts.get(finding.principal_arn) ?? 0) + 1);
  }
  return Array.from(counts.entries())
    .map(([principal, count]) => ({ principal, count }))
    .sort((a, b) => b.count - a.count || a.principal.localeCompare(b.principal))
    .slice(0, limit);
}

/** Faults last-24h split by class (phase-04 §3 Health Tile), aggregated
 * client-side over `GET /operations/faults` -- no dedicated
 * faults-by-class-count endpoint exists.
 */
export function faultsByClass(faults: FaultRecordOut[]): Record<string, number> {
  const out: Record<string, number> = {};
  for (const fault of faults) {
    out[fault.fault_class] = (out[fault.fault_class] ?? 0) + 1;
  }
  return out;
}

export type BreakerTone = "good" | "warning" | "critical";

// `closed` = healthy/green, `half_open` = probing/amber, `open` = tripped/red
// (adapters/src/iam_sentinel_adapters/circuit_breaker.py's `BreakerState`
// Literal). Named "tone" rather than reusing the `Severity` badge variants --
// a breaker isn't a finding severity, it's an operational status, and the
// phase doc §3 explicitly calls out "green/amber/red".
export function breakerTone(state: string): BreakerTone {
  if (state === "closed") return "good";
  if (state === "half_open") return "warning";
  return "critical";
}

export function formatUsd(value: number): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 }).format(
    value,
  );
}

export type TrendDirection = "up" | "down" | "flat";

export interface WeeklyTrend {
  direction: TrendDirection;
  deltaPct: number | null; // null when there's no previous-week figure to compare against
}

/** Trend arrow vs previous week (phase-04 §3 Cost Tile). */
export function weeklyTrend(current: number, previous: number | null): WeeklyTrend {
  if (previous === null || previous === 0) return { direction: "flat", deltaPct: null };
  const deltaPct = ((current - previous) / previous) * 100;
  if (Math.abs(deltaPct) < 1) return { direction: "flat", deltaPct };
  return { direction: deltaPct > 0 ? "up" : "down", deltaPct };
}

/**
 * The weekly cost report's `body` is a free-form dict (`CostReportOut.body:
 * Record<string, unknown>` -- backend never pins its shape beyond that, see
 * `backend/src/iam_sentinel_backend/schemas/operations.py`). This reads the
 * field names the cost-report publisher (agents-phase-09 cost guardrails)
 * is documented to use, defaulting every figure to 0/null rather than
 * throwing, so a differently-shaped or half-published report degrades to
 * "$0.00" tiles instead of crashing the dashboard.
 */
export interface ParsedCostReport {
  bedrockUsd: number;
  athenaUsd: number;
  lambdaUsd: number;
  totalUsd: number;
  previousWeekTotalUsd: number | null;
}

function asNumber(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

export function parseCostReportBody(body: Record<string, unknown>): ParsedCostReport {
  const byService = (body["by_service"] ?? {}) as Record<string, unknown>;
  const bedrockUsd = asNumber(byService["bedrock"] ?? body["bedrock_usd"]);
  const athenaUsd = asNumber(byService["athena"] ?? body["athena_usd"]);
  const lambdaUsd = asNumber(byService["lambda"] ?? body["lambda_usd"]);
  const totalUsdRaw = body["total_usd"];
  const totalUsd = typeof totalUsdRaw === "number" ? totalUsdRaw : bedrockUsd + athenaUsd + lambdaUsd;
  const previous = body["previous_week_usd"];
  return {
    bedrockUsd,
    athenaUsd,
    lambdaUsd,
    totalUsd,
    previousWeekTotalUsd: typeof previous === "number" ? previous : null,
  };
}
