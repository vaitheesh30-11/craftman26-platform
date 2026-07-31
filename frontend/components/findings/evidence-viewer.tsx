"use client";

import { useQuery } from "@tanstack/react-query";

import { apiClient, ApiError } from "@/lib/api-client";
import { evidenceRefFromFinding } from "@/lib/findings-format";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

const RENDER_BUDGET_BYTES = 128 * 1024; // phase-02 §9 risk mitigation

function downloadSignedBlob(ref: string, body: unknown) {
  const blob = new Blob([JSON.stringify(body, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `evidence-${ref}.json`;
  anchor.click();
  URL.revokeObjectURL(url);
}

/**
 * Fetches and verifies a Finding's evidence blob. `GET /evidence/{ref}`
 * (backend phase-04) is being built on another branch -- until it merges,
 * or if the ref genuinely doesn't resolve, this renders a neutral "not
 * available" state instead of crashing (per the explicit ask: 404/502 must
 * degrade gracefully). Never renders `body` for a failed signature check.
 */
export function EvidenceViewer({ evidenceRef }: { evidenceRef: Record<string, unknown> | null }) {
  const ref = evidenceRefFromFinding(evidenceRef);

  const { data, isPending, isError, error } = useQuery({
    queryKey: ["evidence", ref],
    queryFn: () => apiClient.getEvidence(ref as string),
    enabled: ref !== null,
    retry: false,
  });

  if (ref === null) {
    return (
      <section aria-label="Evidence" className="rounded-md border p-3">
        <Badge variant="secondary">No evidence recorded</Badge>
        <p className="mt-2 text-sm text-muted-foreground">
          This finding has no evidence reference attached.
        </p>
      </section>
    );
  }

  if (isPending) {
    return (
      <section aria-label="Evidence" className="space-y-2 rounded-md border p-3">
        <Skeleton className="h-5 w-32" />
        <Skeleton className="h-16 w-full" />
      </section>
    );
  }

  if (isError) {
    const notFound = error instanceof ApiError && error.status === 404;
    return (
      <section aria-label="Evidence" className="rounded-md border p-3">
        <Badge variant="secondary">Evidence not available</Badge>
        <p className="mt-2 text-sm text-muted-foreground">
          {notFound
            ? "This evidence blob could not be found."
            : "Evidence could not be verified right now. It may not be available yet."}
        </p>
      </section>
    );
  }

  if (!data) {
    return null;
  }

  if (!data.verified) {
    return (
      <section aria-label="Evidence" className="rounded-md border border-destructive p-3">
        <Badge variant="destructive">TAMPERED</Badge>
        <p className="mt-2 text-sm text-muted-foreground">
          Signature verification failed for this evidence blob. Its contents are withheld.
        </p>
      </section>
    );
  }

  const json = JSON.stringify(data.body, null, 2);
  const byteSize = new TextEncoder().encode(json).length;
  const truncated = byteSize > RENDER_BUDGET_BYTES;
  const displayJson = truncated ? `${json.slice(0, RENDER_BUDGET_BYTES)}\n… truncated …` : json;

  return (
    <section aria-label="Evidence" className="space-y-2 rounded-md border p-3">
      <div className="flex items-center gap-2">
        <Badge variant="low">Signature verified</Badge>
        <span className="text-xs text-muted-foreground">sha256:{data.sha256.slice(0, 12)}…</span>
      </div>
      <pre className="max-h-96 overflow-auto rounded-md bg-muted/30 p-3 text-xs">
        <code>{displayJson}</code>
      </pre>
      {truncated && (
        <Button type="button" variant="outline" size="sm" onClick={() => downloadSignedBlob(ref, data.body)}>
          Download signed blob
        </Button>
      )}
    </section>
  );
}
