import { getCallerPersona } from "@/lib/principal";
import { DecisionDetail } from "@/components/decisions/decision-detail";

// Server Component (unlike `findings/[id]/page.tsx`'s client-side fetch):
// the caller's group membership only exists server-side inside the id
// token (`lib/principal.ts`), so it's resolved here and handed down as a
// plain prop rather than re-derived in the browser.
export default async function DecisionDetailPage({ params }: { params: { id: string } }) {
  const persona = await getCallerPersona();

  return (
    <main className="container max-w-3xl space-y-6 py-8">
      <DecisionDetail decisionId={params.id} persona={persona} />
    </main>
  );
}
