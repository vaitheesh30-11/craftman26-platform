"use client";

import { useQuery } from "@tanstack/react-query";

import { ApiError, apiClient } from "@/lib/api-client";
import { Skeleton } from "@/components/ui/skeleton";

const PRIME_OVERVIEW_DASHBOARD = "prime_overview";

/**
 * "Deep telemetry" tab (phase-04 §4): embeds the prime-overview CloudWatch
 * dashboard (`aws-infra/dashboards/prime_overview.json`) via an `<iframe>`
 * against a shared-dashboard URL from `GET /operations/dashboards/{name}/
 * share-url`.
 *
 * That endpoint doesn't exist on the backend yet (see
 * `DashboardShareUrlOut`'s doc comment in `lib/api-types.ts`) -- §9's risk
 * mitigation offers a fallback (draw CloudWatch `GetMetricData` client-side
 * with Recharts instead), but that's an equally-unbuilt backend surface,
 * not a smaller lift. Per this phase's own deferral policy (build code-
 * complete against the intended contract; don't fake data for a live-AWS
 * dependency that isn't there), this renders a clear "not available yet"
 * state instead of a broken iframe or fabricated chart, while the fetch +
 * iframe wiring is already correct for the day the endpoint ships.
 */
export function DeepTelemetryTab() {
  const { data, isPending, isError, error } = useQuery({
    queryKey: ["operations", "deep-telemetry", PRIME_OVERVIEW_DASHBOARD],
    queryFn: () => apiClient.getDashboardShareUrl(PRIME_OVERVIEW_DASHBOARD),
    retry: false,
  });

  if (isPending) {
    return <Skeleton className="h-[600px] w-full" />;
  }

  if (isError) {
    const notBuiltYet = error instanceof ApiError && error.status === 404;
    return (
      <div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
        <p>
          {notBuiltYet
            ? "Embedded CloudWatch dashboard isn't available yet -- the backend share-url endpoint hasn't shipped."
            : "Failed to load the embedded CloudWatch dashboard."}
        </p>
        <p className="mt-2">
          See the{" "}
          <code className="rounded bg-muted px-1 py-0.5 text-xs">prime_overview</code> dashboard directly in the
          CloudWatch console in the meantime.
        </p>
      </div>
    );
  }

  return (
    <iframe
      title="Prime overview (CloudWatch)"
      src={data.share_url}
      className="h-[600px] w-full rounded-lg border"
      loading="lazy"
    />
  );
}
