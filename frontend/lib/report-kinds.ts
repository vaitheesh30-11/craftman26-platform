// Single source of truth for report kinds the Reports page filters by
// (frontend phase-04 §5, §7's "report kinds enumerated in a single place;
// drift caught by a snapshot test" contract). `GET /reports/weekly/{kind}`
// takes an unconstrained path string on the backend (no enum --
// `backend/src/iam_sentinel_backend/routers/reports.py`), so this list is a
// frontend-owned contract, not a mirror of a backend enum. `backend/docs/
// phase-04-audit-reports.txt` §3 names `f6`, `cost`, `f2` explicitly; `f8`
// (SLR Breakage Pre-Scanner weekly report) is named by this phase's own spec
// (frontend/docs/phase-04-dashboards.txt §5) even though no agents-phase-09
// (F8) report-publishing code has landed yet -- the page must 404-gracefully
// on it until it does, not omit it and fall short of the "≥ 4 report kinds"
// acceptance criterion.
export interface ReportKindDescriptor {
  kind: string;
  label: string;
  featureId: string | null;
}

export const REPORT_KINDS: readonly ReportKindDescriptor[] = [
  { kind: "cost", label: "Weekly cost", featureId: null },
  { kind: "f2_suppression", label: "F2 suppression", featureId: "F2" },
  { kind: "f6_shadow", label: "F6 shadow-SCP", featureId: "F6" },
  { kind: "f8_slr", label: "F8 SLR breakage", featureId: "F8" },
];
