"use client";

import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";

import { ApiError, apiClient } from "@/lib/api-client";
import { REPORT_KINDS } from "@/lib/report-kinds";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

const LONG_REPORT_THRESHOLD = 20; // top-level keys; above this, summarize instead of dumping raw JSON

function download(filename: string, body: Record<string, unknown>) {
  const blob = new Blob([JSON.stringify(body, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

/**
 * Report preview (phase-04 §5): fetches the latest weekly report for the
 * selected kind (`GET /reports/weekly/{kind}`) and renders it as JSON with
 * a "Download" button. Long reports (many top-level keys) render summary
 * tiles (key -> value-preview rows) instead of a raw dump, per the spec.
 */
export function ReportPreview() {
  const searchParams = useSearchParams();
  const kind = searchParams.get("kind") ?? REPORT_KINDS[0]?.kind ?? "cost";

  const { data, error, isPending, isError } = useQuery({
    queryKey: ["reports", "preview", kind],
    queryFn: () => apiClient.latestWeeklyReport(kind),
    retry: (failureCount, err) => !(err instanceof ApiError && err.status === 404) && failureCount < 1,
  });

  if (isPending) {
    return (
      <div className="space-y-2">
        <Skeleton className="h-6 w-1/3" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  const notPublishedYet = error instanceof ApiError && error.status === 404;
  if (notPublishedYet) {
    return <p className="text-sm text-muted-foreground">No {kind} weekly report has been published yet.</p>;
  }

  if (isError || !data) {
    return <p className="text-sm text-destructive">Failed to load this report.</p>;
  }

  const entries = Object.entries(data.body);
  const isLong = entries.length > LONG_REPORT_THRESHOLD;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="font-mono text-xs text-muted-foreground">{data.retrieved_from_s3_key}</p>
        <Button type="button" size="sm" variant="outline" onClick={() => download(`${kind}.json`, data.body)}>
          Download
        </Button>
      </div>

      {isLong ? (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {entries.map(([key, value]) => (
            <div key={key} className="rounded-md border p-3">
              <p className="text-xs font-semibold uppercase text-muted-foreground">{key}</p>
              <p className="mt-1 truncate text-sm" title={JSON.stringify(value)}>
                {typeof value === "object" ? JSON.stringify(value) : String(value)}
              </p>
            </div>
          ))}
        </div>
      ) : (
        <pre className="max-h-[480px] overflow-auto rounded-md border bg-muted p-4 text-xs">
          {JSON.stringify(data.body, null, 2)}
        </pre>
      )}
    </div>
  );
}
