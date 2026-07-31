import { decodeJwt } from "jose";

import { getCurrentSession } from "@/lib/current-session";

/**
 * Server Component / Route Handler only (imports `lib/current-session.ts`,
 * which imports `next/headers`) -- same runtime boundary as
 * `components/auth-gate.tsx`. The browser never sees the id token, so a
 * client component can't derive its own group membership; this decodes
 * (does not re-verify -- Cognito's signature was already checked at
 * `app/auth/callback/route.ts`'s token exchange, and the session cookie
 * that carries it is itself HS256-signed, see `lib/session.ts`) the
 * `cognito:groups` claim so a Server Component can pass the caller's
 * persona down as a plain prop.
 *
 * Mirrors `backend/src/iam_sentinel_backend/settings.py`'s
 * `cognito_group_operators = "SentinelOperators"` and
 * `auth/breakglass.py`'s `BreakGlass=IAMSentinel-Two-Signer` session tag --
 * this is a *UI* gate only (phase-03 §4's "UI shows ... for other users").
 * Backend does not yet enforce either check on `/decisions/{id}/approve`
 * (see `services/approval_service.py`'s `_APPROVABLE_ACTIONS` -- no
 * group/tag check appears there at all yet); flagged as a gap in this
 * phase's report rather than silently assumed enforced server-side.
 */
export interface CallerPersona {
  groups: string[];
  email: string | null;
  isOperator: boolean;
  isBreakGlass: boolean;
}

const OPERATOR_GROUP = "SentinelOperators";
const BREAKGLASS_GROUP = "SentinelBreakGlass";

export async function getCallerPersona(): Promise<CallerPersona | null> {
  const session = await getCurrentSession();
  if (!session) return null;

  let groups: string[] = [];
  let email: string | null = null;
  try {
    const claims = decodeJwt(session.idToken);
    const rawGroups = claims["cognito:groups"];
    if (Array.isArray(rawGroups)) {
      groups = rawGroups.filter((g): g is string => typeof g === "string");
    }
    email = typeof claims["email"] === "string" ? (claims["email"] as string) : null;
  } catch {
    // Malformed id token -- treat as no groups rather than crashing the
    // decision detail page; the approve button simply stays gated.
    groups = [];
  }

  return {
    groups,
    email,
    isOperator: groups.includes(OPERATOR_GROUP),
    isBreakGlass: groups.includes(BREAKGLASS_GROUP),
  };
}
