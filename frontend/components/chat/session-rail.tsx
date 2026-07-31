"use client";

import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/lib/api-client";
import { Skeleton } from "@/components/ui/skeleton";

// `/decisions/[id]` (phase-02) doesn't exist yet; see result-block.tsx's
// note on sidestepping typedRoutes for forward-referenced routes.
export function SessionRail() {
  const { data, isPending, isError } = useQuery({
    queryKey: ["decisions", "rail"],
    queryFn: () => apiClient.listDecisions({ limit: 20 }),
  });

  return (
    <nav aria-label="Previous sessions" className="flex flex-col gap-2 overflow-y-auto">
      <h2 className="text-xs font-semibold uppercase text-muted-foreground">Previous sessions</h2>
      {isPending && (
        <div className="space-y-2">
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-8 w-full" />
        </div>
      )}
      {isError && <p className="text-xs text-destructive">Failed to load sessions.</p>}
      {data?.items.length === 0 && <p className="text-xs text-muted-foreground">No sessions yet.</p>}
      <ul className="space-y-1">
        {data?.items.map((decision) => (
          <li key={decision.decision_id}>
            <a
              href={`/decisions/${encodeURIComponent(decision.decision_id)}`}
              className="block truncate rounded-md px-2 py-1.5 text-sm hover:bg-accent"
              title={decision.narrative}
            >
              {decision.narrative}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}
