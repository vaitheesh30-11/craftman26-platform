"use client";

import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/lib/api-client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

// Minimal list view (not itself one of phase-03's named deliverables, but
// there is otherwise no in-app link into `decisions/[id]` -- `findings-
// table.tsx`'s "Decision" button stays disabled because `Finding` carries
// no decision reference, see that file's comment). Gives the approval flow
// a discoverable entry point without inventing a decision-search endpoint.
export default function DecisionsPage() {
  const { data, isPending, isError } = useQuery({
    queryKey: ["decisions"],
    queryFn: () => apiClient.listDecisions({ limit: 25 }),
  });

  return (
    <main className="container space-y-6 py-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Decisions</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Every decision Prime has recorded, including any remediations awaiting approval.
        </p>
      </div>

      {isPending && (
        <div className="space-y-2">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      )}
      {isError && <p className="text-sm text-destructive">Failed to load decisions.</p>}
      {data && data.items.length === 0 && (
        <p className="text-sm text-muted-foreground">No decisions have been recorded yet.</p>
      )}
      {data && data.items.length > 0 && (
        <ul className="space-y-2">
          {data.items.map((decision) => (
            <li key={decision.decision_id} className="flex items-center justify-between rounded-md border p-3">
              <div>
                <div className="flex items-center gap-2">
                  <Badge variant="outline">{decision.status}</Badge>
                  <span className="text-xs text-muted-foreground">
                    {new Date(decision.decided_at).toLocaleString()}
                  </span>
                </div>
                <p className="mt-1 max-w-xl truncate text-sm" title={decision.narrative}>
                  {decision.narrative}
                </p>
              </div>
              <Button asChild size="sm" variant="outline">
                <a href={`/decisions/${encodeURIComponent(decision.decision_id)}`}>Open</a>
              </Button>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
