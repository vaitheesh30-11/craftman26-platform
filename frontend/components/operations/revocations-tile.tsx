"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "@/lib/api-client";
import { TileShell } from "@/components/operations/tile-shell";

const QUERY_KEY = ["operations", "revocations-tile"] as const;
const CLICK_THROUGH_HREF = "/findings?feature=F5";

/**
 * Emergency Revocations Tile (phase-04 §3): active revocation count, deep-
 * linking to the F5 (SSO Emergency Session Killer) findings.
 *
 * `docs/DATA_CONTRACTS.md` §"SentinelRevocations (F5)" describes a
 * dedicated DDB table for revocations, but no `/operations/revocations` (or
 * equivalent) endpoint exposes it -- `backend/.../routers/operations.py`
 * only has `/faults`, `/cost/weekly`, `/divergence`, `/health`. This counts
 * F5 findings instead (`GET /findings?feature_id=F5`) as the closest
 * available proxy, which is a real approximation, not the authoritative
 * `SentinelRevocations` count the spec asks for -- every F5 finding isn't
 * necessarily an active revocation. Flagged here rather than silently
 * treated as equivalent; revisit once an operations endpoint over
 * `SentinelRevocations` ships.
 */
export function RevocationsTile() {
  const queryClient = useQueryClient();
  const { data, isPending, isError } = useQuery({
    queryKey: QUERY_KEY,
    queryFn: () => apiClient.listFindings({ feature_id: "F5", limit: 100 }),
    staleTime: 30_000,
    refetchInterval: 60_000,
  });

  const count = data?.items.length ?? 0;

  return (
    <TileShell
      title="Emergency revocations"
      description="F5 findings (proxy for active revocations)"
      href={CLICK_THROUGH_HREF}
      isPending={isPending}
      isError={isError}
      onRefresh={() => queryClient.invalidateQueries({ queryKey: QUERY_KEY })}
    >
      <p className="text-3xl font-semibold tabular-nums">{count}</p>
      <p className="mt-1 text-xs text-muted-foreground">
        No dedicated revocations endpoint yet -- approximated from F5 findings.
      </p>
    </TileShell>
  );
}
