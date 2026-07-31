import { Suspense } from "react";

import { FindingsFilters } from "@/components/findings/findings-filters";
import { FindingsTable } from "@/components/findings/findings-table";

export default function FindingsPage() {
  return (
    <main className="container space-y-6 py-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Findings</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Every finding the eight specialist agents have raised, with its AWS documentation citation.
        </p>
      </div>
      <Suspense fallback={<p className="text-sm text-muted-foreground">Loading filters…</p>}>
        <FindingsFilters />
        <FindingsTable />
      </Suspense>
    </main>
  );
}
