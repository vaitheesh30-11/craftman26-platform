"use client";

import { useState } from "react";
import type { Route } from "next";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import type { Severity } from "@/lib/api-types";
import { FEATURE_IDS, FEATURE_LABELS } from "@/lib/feature-labels";
import { isValidAccountId } from "@/lib/findings-format";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";

const SEVERITIES: Severity[] = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"];
const SINCE_WINDOWS = [
  { value: "24h", label: "Last 24h" },
  { value: "7d", label: "Last 7 days" },
  { value: "30d", label: "Last 30 days" },
  { value: "custom", label: "Custom" },
] as const;

function csv(values: string[]): string | undefined {
  return values.length > 0 ? values.join(",") : undefined;
}

function parseCsv(value: string | null): string[] {
  return value ? value.split(",").filter(Boolean) : [];
}

/**
 * URL-synced filter bar (phase-02 §4, §6): every filter round-trips
 * through `useSearchParams`/`router.push`, so the current view is fully
 * deep-linkable (§8 acceptance criterion). Changing any filter also clears
 * `cursor` -- a filter change invalidates whatever page of results the old
 * cursor pointed into.
 */
export function FindingsFilters() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const selectedSeverities = parseCsv(searchParams.get("severity"));
  const selectedFeatures = parseCsv(searchParams.get("feature"));
  const accountInput = searchParams.get("account") ?? "";
  const sinceWindow = searchParams.get("since") ?? "24h";
  const sinceFrom = searchParams.get("since_from") ?? "";
  const searchInput = searchParams.get("q") ?? "";

  const [accountDraft, setAccountDraft] = useState(accountInput);
  const accountError = accountDraft.length > 0 && !isValidAccountId(accountDraft);

  function setParams(updates: Record<string, string | undefined>) {
    const next = new URLSearchParams(searchParams.toString());
    for (const [key, value] of Object.entries(updates)) {
      if (value === undefined || value === "") next.delete(key);
      else next.set(key, value);
    }
    next.delete("cursor"); // any filter change invalidates the current page
    // `typedRoutes` types `Route<T>` as `string & {}` (next/types) -- an
    // opaque brand, not a real literal-union check at this call site. A
    // filter bar synced to `useSearchParams` can't know its query string
    // statically, so this cast is the documented escape hatch, not a type
    // safety hole specific to this file.
    router.push(`${pathname}?${next.toString()}` as Route);
  }

  function toggle(key: "severity" | "feature", current: string[], value: string) {
    const next = current.includes(value) ? current.filter((v) => v !== value) : [...current, value];
    setParams({ [key]: csv(next) });
  }

  return (
    <div className="space-y-3 rounded-lg border p-4" role="group" aria-label="Findings filters">
      <div>
        <span className="text-xs font-semibold uppercase text-muted-foreground">Severity</span>
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          {SEVERITIES.map((severity) => {
            const active = selectedSeverities.includes(severity);
            return (
              <button
                key={severity}
                type="button"
                aria-pressed={active}
                onClick={() => toggle("severity", selectedSeverities, severity)}
                className="focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <Badge variant={active ? "default" : "outline"}>{severity}</Badge>
              </button>
            );
          })}
        </div>
      </div>

      <div>
        <span className="text-xs font-semibold uppercase text-muted-foreground">Feature</span>
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          {FEATURE_IDS.map((feature) => {
            const active = selectedFeatures.includes(feature);
            return (
              <button
                key={feature}
                type="button"
                aria-pressed={active}
                title={FEATURE_LABELS[feature]}
                onClick={() => toggle("feature", selectedFeatures, feature)}
                className="focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <Badge variant={active ? "default" : "outline"}>{feature}</Badge>
              </button>
            );
          })}
        </div>
      </div>

      <div className="flex flex-wrap items-end gap-4">
        <div>
          <label htmlFor="findings-account" className="text-xs font-semibold uppercase text-muted-foreground">
            Account ID
          </label>
          <Input
            id="findings-account"
            inputMode="numeric"
            placeholder="123456789012"
            value={accountDraft}
            className="mt-1.5 h-9 w-40"
            onChange={(e) => setAccountDraft(e.target.value)}
            onBlur={() => {
              if (accountDraft === "" || isValidAccountId(accountDraft)) setParams({ account: accountDraft });
            }}
            aria-invalid={accountError}
          />
          {accountError && <p className="mt-1 text-xs text-destructive">Must be exactly 12 digits.</p>}
        </div>

        <div>
          <span className="text-xs font-semibold uppercase text-muted-foreground">Since</span>
          <div className="mt-1.5 flex gap-1.5">
            {SINCE_WINDOWS.map((window) => (
              <button
                key={window.value}
                type="button"
                aria-pressed={sinceWindow === window.value}
                onClick={() => setParams({ since: window.value })}
              >
                <Badge variant={sinceWindow === window.value ? "default" : "outline"}>{window.label}</Badge>
              </button>
            ))}
          </div>
        </div>

        {sinceWindow === "custom" && (
          <div>
            <label htmlFor="findings-since-from" className="text-xs font-semibold uppercase text-muted-foreground">
              From
            </label>
            <Input
              id="findings-since-from"
              type="date"
              value={sinceFrom}
              className="mt-1.5 h-9"
              onChange={(e) => setParams({ since_from: e.target.value })}
            />
          </div>
        )}

        <div className="flex-1">
          <label htmlFor="findings-search" className="text-xs font-semibold uppercase text-muted-foreground">
            Search (title / detail)
          </label>
          <Input
            id="findings-search"
            placeholder="Search this page's results…"
            defaultValue={searchInput}
            className="mt-1.5 h-9"
            onChange={(e) => setParams({ q: e.target.value })}
          />
        </div>
      </div>
    </div>
  );
}
