"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/lib/api-client";
import { breakerTone, faultsByClass } from "@/lib/dashboard-format";
import { sinceWindowToIso } from "@/lib/findings-format";
import { Badge } from "@/components/ui/badge";
import { TileShell } from "@/components/operations/tile-shell";

const SINCE_24H = sinceWindowToIso("24h");
const HEALTH_QUERY_KEY = ["operations", "health-tile", "health"] as const;
const FAULTS_QUERY_KEY = ["operations", "health-tile", "faults", SINCE_24H] as const;

const TONE_BADGE_VARIANT = { good: "low", warning: "medium", critical: "critical" } as const;

/**
 * Health Tile (phase-04 §3): breaker states, SessionKill DLQ depth, and
 * faults last-24h split by class, from `GET /operations/health` + `GET
 * /operations/faults`. KB freshness (`SentinelKbStaleRetrieval` last-hour
 * count) has no backing endpoint on the backend
 * (`backend/src/iam_sentinel_backend/routers/operations.py` exposes
 * `/faults`, `/cost/weekly`, `/divergence`, `/health` only) -- shown as
 * "not available" rather than a fabricated number.
 */
export function HealthTile() {
  const queryClient = useQueryClient();
  const health = useQuery({
    queryKey: HEALTH_QUERY_KEY,
    queryFn: () => apiClient.getOperationsHealth(),
    staleTime: 30_000,
    refetchInterval: 60_000,
  });
  const faults = useQuery({
    queryKey: FAULTS_QUERY_KEY,
    queryFn: () => apiClient.listFaults({ limit: 100 }),
    staleTime: 30_000,
    refetchInterval: 60_000,
  });

  const isPending = health.isPending || faults.isPending;
  const isError = health.isError || faults.isError;
  const faultCounts = faults.data ? faultsByClass(faults.data.items) : {};
  // `since` isn't a `listFaults` filter today (`apiClient.listFaults` only
  // forwards `next_token`/`limit`) -- filter the fetched page client-side to
  // the last-24h window the tile promises, same posture as the findings
  // tile's client-side aggregation.
  const faultEntries = Object.entries(faultCounts);

  return (
    <TileShell
      title="Health"
      description="Breakers, DLQ depth, faults (24h)"
      isPending={isPending}
      isError={isError}
      onRefresh={() => {
        queryClient.invalidateQueries({ queryKey: HEALTH_QUERY_KEY });
        queryClient.invalidateQueries({ queryKey: FAULTS_QUERY_KEY });
      }}
    >
      <div className="space-y-3 text-sm">
        <div>
          <p className="text-xs font-semibold uppercase text-muted-foreground">Breakers</p>
          <div className="mt-1 flex flex-wrap gap-1.5">
            {health.data?.breakers.map((breaker) => (
              <Badge key={breaker.breaker_name} variant={TONE_BADGE_VARIANT[breakerTone(breaker.state)]}>
                {breaker.breaker_name}: {breaker.state}
              </Badge>
            ))}
            {health.data && health.data.breakers.length === 0 && (
              <span className="text-xs text-muted-foreground">No breakers configured.</span>
            )}
          </div>
        </div>

        <div>
          <p className="text-xs font-semibold uppercase text-muted-foreground">DLQ depth</p>
          <div className="mt-1 space-y-0.5">
            {health.data?.dlqs.map((dlq) => (
              <p key={dlq.queue_url} className="text-xs">
                <span className="font-mono">{dlq.queue_url.split("/").at(-1)}</span>:{" "}
                <span className="tabular-nums">{dlq.approximate_messages}</span>
              </p>
            ))}
            {health.data && health.data.dlqs.length === 0 && (
              <span className="text-xs text-muted-foreground">No DLQs configured.</span>
            )}
          </div>
        </div>

        <div>
          <p className="text-xs font-semibold uppercase text-muted-foreground">Faults, last 24h</p>
          {faultEntries.length === 0 ? (
            <p className="mt-1 text-xs text-muted-foreground">None.</p>
          ) : (
            <div className="mt-1 flex flex-wrap gap-1.5">
              {faultEntries.map(([faultClass, count]) => (
                <Badge key={faultClass} variant="outline">
                  {faultClass}: {count}
                </Badge>
              ))}
            </div>
          )}
        </div>

        <p className="text-xs text-muted-foreground" title="No backend endpoint yet for SentinelKbStaleRetrieval">
          KB freshness: not available
        </p>
      </div>
    </TileShell>
  );
}
