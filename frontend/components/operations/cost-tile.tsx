"use client";

import { ArrowDown, ArrowRight, ArrowUp } from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, apiClient } from "@/lib/api-client";
import { formatUsd, parseCostReportBody, weeklyTrend } from "@/lib/dashboard-format";
import { TileShell } from "@/components/operations/tile-shell";

const QUERY_KEY = ["operations", "cost-tile"] as const;

const TREND_ICON = { up: ArrowUp, down: ArrowDown, flat: ArrowRight } as const;
// Cost going up is bad (destructive), down is good, flat is neutral --
// opposite of a typical revenue trend arrow, so this isn't reused from
// `lib/dashboard-format.ts`'s generic `TrendDirection`.
const TREND_CLASS = {
  up: "text-destructive",
  down: "text-severity-low",
  flat: "text-muted-foreground",
} as const;

/**
 * Cost Tile (phase-04 §3, §9 risk mitigation): weekly Bedrock + Athena +
 * Lambda $ from the latest published cost report (`GET
 * /operations/cost/weekly`), with a trend arrow vs the previous week.
 * `report.body` is a free-form dict (see `ParsedCostReport`'s doc comment)
 * -- there's no `GetMetricData`-backed near-real-time MTD figure yet (§9's
 * second mitigation), so this tile only shows the weekly-cadence figure and
 * says so rather than fabricating an MTD number. A 404 (`COST_REPORT_NOT_
 * FOUND` -- no report published yet) is rendered as an empty state, not the
 * generic error state; any other failure is.
 */
export function CostTile() {
  const queryClient = useQueryClient();
  const { data, error, isPending, isError } = useQuery({
    queryKey: QUERY_KEY,
    queryFn: () => apiClient.latestCostReport(),
    staleTime: 30_000,
    refetchInterval: 60_000,
    retry: (failureCount, err) => !(err instanceof ApiError && err.status === 404) && failureCount < 1,
  });

  const notPublishedYet = error instanceof ApiError && error.status === 404;
  const parsed = data ? parseCostReportBody(data.body) : null;
  const trend = parsed ? weeklyTrend(parsed.totalUsd, parsed.previousWeekTotalUsd) : null;
  const TrendIcon = trend ? TREND_ICON[trend.direction] : null;

  return (
    <TileShell
      title="Cost"
      description="Weekly Bedrock + Athena + Lambda"
      href="/reports/cost/weekly/latest"
      isPending={isPending}
      isError={isError && !notPublishedYet}
      onRefresh={() => queryClient.invalidateQueries({ queryKey: QUERY_KEY })}
    >
      {notPublishedYet && <p className="text-sm text-muted-foreground">No cost report published yet.</p>}
      {parsed && (
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <p className="text-3xl font-semibold tabular-nums">{formatUsd(parsed.totalUsd)}</p>
            {TrendIcon && trend && (
              <span className={`flex items-center gap-0.5 text-sm ${TREND_CLASS[trend.direction]}`}>
                <TrendIcon className="h-4 w-4" />
                {trend.deltaPct !== null ? `${Math.abs(trend.deltaPct).toFixed(1)}%` : "—"}
              </span>
            )}
          </div>
          <dl className="grid grid-cols-3 gap-2 text-xs text-muted-foreground">
            <div>
              <dt>Bedrock</dt>
              <dd className="font-medium text-foreground">{formatUsd(parsed.bedrockUsd)}</dd>
            </div>
            <div>
              <dt>Athena</dt>
              <dd className="font-medium text-foreground">{formatUsd(parsed.athenaUsd)}</dd>
            </div>
            <div>
              <dt>Lambda</dt>
              <dd className="font-medium text-foreground">{formatUsd(parsed.lambdaUsd)}</dd>
            </div>
          </dl>
        </div>
      )}
    </TileShell>
  );
}
