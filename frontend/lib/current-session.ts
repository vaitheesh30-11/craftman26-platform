import { cookies } from "next/headers";

import { SESSION_COOKIE_NAME, verifySessionCookieValue, type SessionPayload } from "@/lib/session";

/**
 * Server Component / Route Handler only. Distinct from `lib/session.ts`'s
 * cookie codec so that module stays pure (no `next/headers` import) and
 * is trivially unit-testable outside a request context.
 */
export async function getCurrentSession(): Promise<SessionPayload | null> {
  const value = cookies().get(SESSION_COOKIE_NAME)?.value;
  if (!value) return null;
  return verifySessionCookieValue(value);
}
