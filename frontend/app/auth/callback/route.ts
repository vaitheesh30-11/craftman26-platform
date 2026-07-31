import { cookies } from "next/headers";
import { NextResponse, type NextRequest } from "next/server";

import { exchangeCodeForTokens, CognitoTokenExchangeError } from "@/lib/auth";
import {
  createSessionCookieValue,
  generateCsrfToken,
  SESSION_COOKIE_MAX_AGE_SECONDS,
  SESSION_COOKIE_NAME,
  CSRF_COOKIE_NAME,
} from "@/lib/session";
import { OAUTH_STATE_COOKIE } from "@/app/auth/login/page";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Cognito hosted-UI OAuth2 code-exchange endpoint (phase-00 §3). Runs
 * entirely server-side: the authorization `code` never reaches client JS,
 * and neither does the resulting token bundle — it's sealed into the
 * HttpOnly session cookie here and nowhere else.
 */
export async function GET(request: NextRequest): Promise<NextResponse> {
  const url = request.nextUrl;
  const code = url.searchParams.get("code");
  const state = url.searchParams.get("state");
  const errorParam = url.searchParams.get("error");

  const cookieStore = cookies();
  const expectedState = cookieStore.get(OAUTH_STATE_COOKIE)?.value;
  cookieStore.delete(OAUTH_STATE_COOKIE);

  if (errorParam) {
    return NextResponse.redirect(new URL(`/auth/login?error=${encodeURIComponent(errorParam)}`, url));
  }
  if (!code || !state || !expectedState || state !== expectedState) {
    return NextResponse.redirect(new URL("/auth/login?error=invalid_state", url));
  }

  try {
    const tokens = await exchangeCodeForTokens(code);
    const sessionValue = await createSessionCookieValue(tokens);
    const csrfToken = generateCsrfToken();

    const response = NextResponse.redirect(new URL("/", url));
    response.cookies.set(SESSION_COOKIE_NAME, sessionValue, {
      httpOnly: true,
      secure: process.env.NODE_ENV === "production",
      sameSite: "lax",
      path: "/",
      maxAge: SESSION_COOKIE_MAX_AGE_SECONDS,
    });
    // Double-submit CSRF cookie: deliberately NOT HttpOnly (the client
    // must read it to echo it back as `x-csrf-token`; see lib/api-client.ts).
    response.cookies.set(CSRF_COOKIE_NAME, csrfToken, {
      httpOnly: false,
      secure: process.env.NODE_ENV === "production",
      sameSite: "lax",
      path: "/",
      maxAge: SESSION_COOKIE_MAX_AGE_SECONDS,
    });
    return response;
  } catch (error) {
    const status = error instanceof CognitoTokenExchangeError ? error.status : 500;
    return NextResponse.redirect(
      new URL(`/auth/login?error=token_exchange_failed&status=${status}`, url),
    );
  }
}
