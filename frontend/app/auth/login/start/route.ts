import { randomBytes } from "node:crypto";

import { NextResponse } from "next/server";

import { buildHostedUiSignInUrl } from "@/lib/auth";
import { OAUTH_STATE_COOKIE } from "@/lib/oauth-state";

export const dynamic = "force-dynamic";

/**
 * Mints the OAuth CSRF `state` and stores it in a short-lived HttpOnly
 * cookie before redirecting to Cognito's hosted UI. Cookie writes are only
 * legal in a Server Action or Route Handler (Next.js App Router) -- this
 * used to happen inline in the `/auth/login` page's render, which throws
 * at request time in a real browser (caught only once this app was
 * actually launched; every prior toolchain run mocked next/headers or
 * skipped Playwright entirely).
 */
export function GET(): NextResponse {
  const state = randomBytes(16).toString("hex");
  const response = NextResponse.redirect(buildHostedUiSignInUrl(state));
  response.cookies.set(OAUTH_STATE_COOKIE, state, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: 300,
  });
  return response;
}
