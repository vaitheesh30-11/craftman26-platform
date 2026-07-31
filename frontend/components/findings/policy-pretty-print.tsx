// Generic JSON pretty-printer used for policy documents (F3's merged
// policy, F8's safe_scp diff, etc.) and as the honest fallback for every
// feature payload whose shape isn't finalized in this codebase yet (see
// `finding-detail.tsx`'s comment on F2-F8 payload rendering).
export function PolicyPrettyPrint({ document, label }: { document: unknown; label?: string }) {
  const json = JSON.stringify(document, null, 2);
  const byteSize = new TextEncoder().encode(json).length;

  return (
    <div className="rounded-md border bg-muted/30">
      <div className="flex items-center justify-between border-b px-3 py-1.5 text-xs text-muted-foreground">
        <span>{label ?? "Policy document"}</span>
        <span>{byteSize.toLocaleString()} bytes</span>
      </div>
      <pre className="max-h-96 overflow-auto p-3 text-xs">
        <code>{json}</code>
      </pre>
    </div>
  );
}
