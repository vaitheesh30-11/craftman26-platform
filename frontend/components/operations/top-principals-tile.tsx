"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/lib/api-client";
import { topPrincipals } from "@/lib/dashboard-format";
import { shortArn, sinceWindowToIso } from "@/lib/findings-format";
import { TileShell } from "@/components/operations/tile-shell";

const SINCE_7D = sinceWindowToIso("7d");
const QUERY_KEY = ["operations", "top-principals-tile", SINCE_7D] as const;

/**
 * Top Principals Tile (phase-04 §3): top 5 principals by finding count over
 * the last 7 days. No `/operations/top-principals` aggregate endpoint
 * exists -- aggregated client-side over `GET /findings?since=7d`
 * (`lib/dashboard-format.ts#topPrincipals`), same posture as the Findings
 * Tile.
 */
export function TopPrincipalsTile() {
  const queryClient = useQueryClient();
  const { data, isPending, isError } = useQuery({
    queryKey: QUERY_KEY,
    queryFn: () => apiClient.listFindings({ since: SINCE_7D, limit: 100 }),
    staleTime: 30_000,
    refetchInterval: 60_000,
  });

  const top = data ? topPrincipals(data.items, 5) : [];

  return (
    <TileShell
      title="Top principals"
      description="By finding count, last 7 days"
      isPending={isPending}
      isError={isError}
      onRefresh={() => queryClient.invalidateQueries({ queryKey: QUERY_KEY })}
    >
      {top.length === 0 ? (
        <p className="text-sm text-muted-foreground">No attributable findings in this window.</p>
      ) : (
        <ol className="space-y-1.5 text-sm">
          {top.map(({ principal, count }) => (
            <li key={principal} className="flex items-center justify-between gap-2">
              <a
                href={`/findings?principal_arn=${encodeURIComponent(principal)}`}
                className="truncate font-mono text-xs hover:underline"
                title={principal}
              >
                {shortArn(principal)}
              </a>
              <span className="tabular-nums text-muted-foreground">{count}</span>
            </li>
          ))}
        </ol>
      )}
    </TileShell>
  );
}
