import type { FindingOut } from "@/lib/api-types";
import { shortArn } from "@/lib/findings-format";
import { FEATURE_LABELS } from "@/lib/feature-labels";
import { Badge } from "@/components/ui/badge";
import { CitationInline } from "@/components/chat/citation-inline";
import { SeverityBadge } from "@/components/findings/severity-badge";
import { EvidenceViewer } from "@/components/findings/evidence-viewer";
import { PolicyPrettyPrint } from "@/components/findings/policy-pretty-print";

// Ordered list of blast-radius hops, if the producer populated F1's
// documented `blast_path` shape (an array of ARN-ish strings/hop objects).
// Every other feature (F2-F8) falls back to a labeled JSON block below --
// those payload shapes aren't finalized in this codebase yet (they're
// defined per-feature in agents/docs/phase-0{3..9}-*.txt, not here), so a
// generic pretty-print is the honest thing to ship rather than guessing at
// fields that don't exist yet.
function BlastPath({ blastPath }: { blastPath: unknown[] }) {
  return (
    <ol className="ml-4 list-decimal space-y-1 text-sm">
      {blastPath.map((hop, index) => (
        <li key={index}>
          {typeof hop === "string" ? hop : <code className="text-xs">{JSON.stringify(hop)}</code>}
        </li>
      ))}
    </ol>
  );
}

function FeaturePayload({ finding }: { finding: FindingOut }) {
  const blastPath = finding.payload["blast_path"];
  if (finding.feature_id === "F1" && Array.isArray(blastPath) && blastPath.length > 0) {
    return <BlastPath blastPath={blastPath} />;
  }
  if (Object.keys(finding.payload).length === 0) {
    return <p className="text-sm text-muted-foreground">No payload attached to this finding.</p>;
  }
  return <PolicyPrettyPrint document={finding.payload} label={`${finding.feature_id} payload`} />;
}

export function FindingDetail({ finding }: { finding: FindingOut }) {
  return (
    <article className="space-y-6">
      <header className="space-y-2">
        <div className="flex items-center gap-2">
          <SeverityBadge severity={finding.severity} />
          <Badge variant="secondary" title={FEATURE_LABELS[finding.feature_id]}>
            {finding.feature_id}
          </Badge>
          <Badge variant="outline">{finding.status}</Badge>
        </div>
        <h1 className="text-xl font-semibold tracking-tight">{finding.title}</h1>
        <p className="text-xs text-muted-foreground">
          {finding.account_id} · {shortArn(finding.principal_arn ?? finding.resource_arn)} ·{" "}
          {new Date(finding.detected_at).toLocaleString()}
        </p>
      </header>

      {/* The citation is this platform's most important UX element (phase-02
          §5) -- it's the proof a Finding traces back to real AWS docs, not
          a model's assertion. Rendered first, in its own callout, not
          buried under the body text. */}
      <section aria-label="AWS documentation citation" className="rounded-lg border-2 border-primary/40 bg-primary/5 p-4">
        <p className="text-xs font-semibold uppercase text-primary">AWS documentation citation</p>
        <CitationInline citation={finding.aws_doc_citation} />
      </section>

      <section aria-label="Finding detail">
        <h2 className="text-sm font-semibold">Detail</h2>
        <p className="mt-1 whitespace-pre-wrap text-sm">{finding.detail}</p>
      </section>

      <section aria-label="Feature-specific payload">
        <h2 className="text-sm font-semibold">Payload ({finding.feature_id})</h2>
        <div className="mt-1">
          <FeaturePayload finding={finding} />
        </div>
      </section>

      <section aria-label="Evidence">
        <h2 className="text-sm font-semibold">Evidence</h2>
        <div className="mt-1">
          <EvidenceViewer evidenceRef={finding.evidence_ref} />
        </div>
      </section>

      <section aria-label="Related">
        <h2 className="text-sm font-semibold">Related</h2>
        {/* `Finding` carries no `decision_id`/`correlation_id`
            (docs/DATA_CONTRACTS.md §4) -- a real link to the DecisionRecord
            that produced this finding isn't derivable from this response
            alone. A verified evidence body does carry `correlation_id`
            (§6 `EvidenceRecord`), which is the closest honest lead until
            a decision-search endpoint exists. */}
        <p className="mt-1 text-sm text-muted-foreground">
          No direct decision link is available in this schema yet. If the evidence above verifies, its correlation ID
          can be used to locate the originating decision once decision search ships.
        </p>
      </section>
    </article>
  );
}
