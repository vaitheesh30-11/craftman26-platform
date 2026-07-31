"use client";

import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/lib/api-client";
import { Skeleton } from "@/components/ui/skeleton";
import { FindingDetail } from "@/components/findings/finding-detail";

export default function FindingDetailPage({ params }: { params: { id: string } }) {
  const { data, isPending, isError } = useQuery({
    queryKey: ["finding", params.id],
    queryFn: () => apiClient.getFinding(params.id),
  });

  return (
    <main className="container max-w-3xl space-y-6 py-8">
      {isPending && (
        <div className="space-y-3">
          <Skeleton className="h-8 w-1/2" />
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      )}
      {isError && <p className="text-sm text-destructive">Failed to load this finding.</p>}
      {data && <FindingDetail finding={data} />}
    </main>
  );
}
