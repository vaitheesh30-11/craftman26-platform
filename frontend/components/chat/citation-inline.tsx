import type { AwsDocCitationOut } from "@/lib/api-types";

export function CitationInline({ citation }: { citation: AwsDocCitationOut }) {
  return (
    <blockquote className="mt-2 border-l-2 border-muted pl-3 text-xs text-muted-foreground">
      <p className="italic">&ldquo;{citation.quote}&rdquo;</p>
      <p className="mt-1">
        <a href={citation.url} target="_blank" rel="noreferrer" className="underline hover:text-foreground">
          {citation.source}
        </a>{" "}
        &middot; retrieved {citation.retrieved_on}
      </p>
    </blockquote>
  );
}
