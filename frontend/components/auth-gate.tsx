import { redirect } from "next/navigation";

import { getCurrentSession } from "@/lib/current-session";

/**
 * Server Component gate (phase-00 §3: "AuthGate redirects unauthenticated
 * users to /auth/login"). Runs on every request to a gated route because
 * it reads the HttpOnly session cookie directly — no client-side flash of
 * protected content followed by a redirect.
 */
export async function AuthGate({ children }: { children: React.ReactNode }) {
  const session = await getCurrentSession();
  if (!session) {
    redirect("/auth/login");
  }
  return <>{children}</>;
}
