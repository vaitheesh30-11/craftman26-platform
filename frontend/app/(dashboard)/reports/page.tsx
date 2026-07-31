import { Suspense } from "react";

import { ReportList } from "@/components/reports/report-list";
import { ReportPreview } from "@/components/reports/report-preview";

export default function ReportsPage() {
  return (
    <main className="container max-w-3xl space-y-6 py-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Reports</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Weekly reports published by Sentinel&rsquo;s specialists and audit surfaces.
        </p>
      </div>
      <Suspense fallback={<p className="text-sm text-muted-foreground">Loading…</p>}>
        <ReportList />
        <ReportPreview />
      </Suspense>
    </main>
  );
}
