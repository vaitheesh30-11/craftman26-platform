"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis } from "recharts";

import { apiClient } from "@/lib/api-client";
import { countAtLeastMedium, severityWeightedSparkline } from "@/lib/dashboard-format";
import { sinceWindowToIso } from "@/lib/findings-format";
import { TileShell } from "@/components/operations/tile-shell";

const SINCE_7D = sinceWindowToIso("7d");
const QUERY_KEY = ["operations", "findings-tile", SINCE_7D] as const;
const CLICK_THROUGH_HREF = "/findings?severity=CRITICAL,HIGH,MEDIUM&since=7d";

/**
 * Findings Tile (phase-04 §3): count of open findings severity >= MEDIUM in
 * the last 7 days, plus a severity-weighted sparkline. `GET /findings` has
 * no severity->=MEDIUM or count-only mode (`backend/.../routers/findings.py`
 * only filters on a single exact `severity` value), so this fetches the
 * unfiltered last-7d page (capped at 100, the backend's max `limit`) and
 * aggregates client-side -- same posture as `FindingsTable`'s multi-select
 * workaround.
 */
export function FindingsTile() {
  const queryClient = useQueryClient();
  const { data, isPending, isError } = useQuery({
    queryKey: QUERY_KEY,
    queryFn: () => apiClient.listFindings({ since: SINCE_7D, limit: 100 }),
    staleTime: 30_000,
    refetchInterval: 60_000,
  });

  const items = data?.items ?? [];
  const openCount = countAtLeastMedium(items);
  const sparkline = severityWeightedSparkline(items, 7);

  return (
    <TileShell
      title="Findings"
      description="Open, severity ≥ MEDIUM, last 7 days"
      href={CLICK_THROUGH_HREF}
      isPending={isPending}
      isError={isError}
      onRefresh={() => queryClient.invalidateQueries({ queryKey: QUERY_KEY })}
    >
      <div className="flex items-end gap-4">
        <p className="text-3xl font-semibold tabular-nums">{openCount}</p>
        <div className="h-12 flex-1">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={sparkline} margin={{ top: 4, right: 4, bottom: 0, left: 4 }}>
              <XAxis dataKey="date" hide />
              <Tooltip
                formatter={(value: number) => [value, "Severity-weighted score"]}
                labelFormatter={(label: string) => label}
                contentStyle={{ fontSize: 12 }}
              />
              <Line
                type="monotone"
                dataKey="value"
                stroke="hsl(var(--primary))"
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    </TileShell>
  );
}
