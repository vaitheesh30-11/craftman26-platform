"use client";

import { useState } from "react";
import type { Route } from "next";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";

import { apiClient } from "@/lib/api-client";
import type { FindingOut } from "@/lib/api-types";
import { maskAccountId, severityRank, shortArn, sinceWindowToIso } from "@/lib/findings-format";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { SeverityBadge } from "@/components/findings/severity-badge";
import { useToast } from "@/components/ui/use-toast";

const PAGE_SIZE = 25;

function parseCsv(value: string | null): string[] {
  return value ? value.split(",").filter(Boolean) : [];
}

interface FindingsQueryParams {
  severity?: string;
  feature_id?: string;
  account_id?: string;
  since?: string;
  limit: number;
  next_token?: string;
}

/**
 * `GET /findings` only accepts one `severity`/`feature_id` value each
 * (backend/src/iam_sentinel_backend/routers/findings.py) -- there's no
 * server-side multi-select yet. When exactly one value is selected for a
 * dimension we forward it (cheapest, most correct); when zero or several
 * are selected we fetch unfiltered on that dimension and narrow client-side
 * after the fact, same posture as the free-text search the phase doc
 * explicitly allows to be client-side "until backend supports" it.
 */
function buildQueryParams(searchParams: URLSearchParams): FindingsQueryParams {
  const severities = parseCsv(searchParams.get("severity"));
  const features = parseCsv(searchParams.get("feature"));
  const account = searchParams.get("account") ?? "";
  const sinceWindow = searchParams.get("since") ?? "24h";
  const sinceFrom = searchParams.get("since_from");

  return {
    severity: severities.length === 1 ? severities[0] : undefined,
    feature_id: features.length === 1 ? features[0] : undefined,
    account_id: account.length === 12 ? account : undefined,
    since: sinceWindow === "custom" ? (sinceFrom ? new Date(sinceFrom).toISOString() : undefined) : sinceWindowToIso(sinceWindow),
    limit: PAGE_SIZE,
    next_token: searchParams.get("cursor") ?? undefined,
  };
}

function applyClientSideFilters(items: FindingOut[], searchParams: URLSearchParams): FindingOut[] {
  const severities = parseCsv(searchParams.get("severity"));
  const features = parseCsv(searchParams.get("feature"));
  const q = (searchParams.get("q") ?? "").trim().toLowerCase();

  return items
    .filter((item) => severities.length === 0 || severities.includes(item.severity))
    .filter((item) => features.length === 0 || features.includes(item.feature_id))
    .filter(
      (item) => q === "" || item.title.toLowerCase().includes(q) || item.detail.toLowerCase().includes(q),
    )
    .slice()
    .sort((a, b) => severityRank(b.severity) - severityRank(a.severity) || b.detected_at.localeCompare(a.detected_at));
}

export function FindingsTable() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [revealedAccounts, setRevealedAccounts] = useState<Set<string>>(new Set());
  const [cursorStack, setCursorStack] = useState<(string | undefined)[]>([]);

  const params = buildQueryParams(searchParams);
  const queryKey = ["findings", params] as const;

  const { data, isPending, isError } = useQuery({
    queryKey,
    queryFn: () => apiClient.listFindings(params),
  });

  const hasAnyFilter =
    searchParams.get("severity") ||
    searchParams.get("feature") ||
    searchParams.get("account") ||
    searchParams.get("q") ||
    (searchParams.get("since") ?? "24h") !== "24h";

  const rows = data ? applyClientSideFilters(data.items, searchParams) : [];

  function goToPage(nextToken: string | undefined, direction: "next" | "prev") {
    const next = new URLSearchParams(searchParams.toString());
    if (nextToken) next.set("cursor", nextToken);
    else next.delete("cursor");
    if (direction === "next") setCursorStack((stack) => [...stack, params.next_token]);
    else setCursorStack((stack) => stack.slice(0, -1));
    router.push(`/findings?${next.toString()}` as Route);
  }

  function prefetchNext() {
    if (!data?.next_token) return;
    void queryClient.prefetchQuery({
      queryKey: ["findings", { ...params, next_token: data.next_token }],
      queryFn: () => apiClient.listFindings({ ...params, next_token: data.next_token ?? undefined }),
    });
  }

  async function copyCorrelationId() {
    // Finding has no `correlation_id` field (docs/DATA_CONTRACTS.md §4) --
    // it only exists on `EvidenceRecord`/`DecisionRecord`. There's no
    // per-row correlation id to copy without an extra evidence fetch per
    // row, which isn't worth the request volume for a table action. Being
    // explicit about the gap rather than fabricating an id.
    toast({
      title: "Not available",
      description: "Findings don't carry a correlation_id directly -- open the finding's evidence to find one.",
    });
  }

  if (isPending) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))}
      </div>
    );
  }

  if (isError) {
    return <p className="text-sm text-destructive">Failed to load findings.</p>;
  }

  if (rows.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        {hasAnyFilter
          ? "No findings match the current filters."
          : "No findings have been recorded yet."}
      </p>
    );
  }

  return (
    <div className="space-y-3">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Severity</TableHead>
            <TableHead>Feature</TableHead>
            <TableHead>Account</TableHead>
            <TableHead>Subject</TableHead>
            <TableHead>Title</TableHead>
            <TableHead>Detected</TableHead>
            <TableHead>Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((finding) => {
            const revealed = revealedAccounts.has(finding.finding_id);
            return (
              <TableRow key={finding.finding_id}>
                <TableCell>
                  <SeverityBadge severity={finding.severity} />
                </TableCell>
                <TableCell title={finding.feature_id}>
                  <Badge variant="secondary">{finding.feature_id}</Badge>
                </TableCell>
                <TableCell>
                  <button
                    type="button"
                    className="font-mono text-xs underline-offset-2 hover:underline"
                    onClick={() =>
                      setRevealedAccounts((prev) => {
                        const next = new Set(prev);
                        if (next.has(finding.finding_id)) next.delete(finding.finding_id);
                        else next.add(finding.finding_id);
                        return next;
                      })
                    }
                  >
                    {maskAccountId(finding.account_id, revealed)}
                  </button>
                </TableCell>
                <TableCell className="text-xs">{shortArn(finding.principal_arn ?? finding.resource_arn)}</TableCell>
                <TableCell className="max-w-xs truncate" title={finding.title}>
                  {finding.title}
                </TableCell>
                <TableCell
                  className="whitespace-nowrap text-xs text-muted-foreground"
                  title={new Date(finding.detected_at).toLocaleString()}
                >
                  {new Date(finding.detected_at).toLocaleDateString()}
                </TableCell>
                <TableCell>
                  <div className="flex gap-1">
                    <Button asChild size="sm" variant="outline">
                      <a href={`/findings/${encodeURIComponent(finding.finding_id)}`}>Open</a>
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      title="Findings don't carry a decision reference yet (docs/DATA_CONTRACTS.md §4)"
                      disabled
                    >
                      Decision
                    </Button>
                    <Button type="button" size="sm" variant="ghost" onClick={copyCorrelationId}>
                      Copy ID
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>

      <div className="flex items-center justify-between">
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={cursorStack.length === 0}
          onClick={() => goToPage(cursorStack.at(-1), "prev")}
        >
          Previous
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={!data?.next_token}
          onMouseEnter={prefetchNext}
          onClick={() => goToPage(data?.next_token ?? undefined, "next")}
        >
          Next
        </Button>
      </div>
    </div>
  );
}
