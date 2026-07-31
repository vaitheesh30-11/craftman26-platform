import { randomBytes } from "node:crypto";

import { SignJWT, jwtVerify } from "jose";

import { getServerEnv } from "@/lib/env";
import type { CognitoTokenResponse } from "@/lib/auth";

export const SESSION_COOKIE_NAME = "sentinel_session";
export const CSRF_COOKIE_NAME = "sentinel_csrf";

export interface SessionPayload {
  accessToken: string;
  idToken: string;
  refreshToken?: string;
}

// `Buffer.from` (Node-realm `Uint8Array`), not `new TextEncoder().encode`:
// under a jsdom test environment, the global `TextEncoder` is jsdom's own
// implementation, and its output fails `jose`'s cross-realm
// `instanceof Uint8Array` check against Node's `Uint8Array`. `Buffer` is
// always Node's, in every runtime this module actually runs in (Route
// Handlers, Server Components, and Vitest/jsdom).
function secretKey(): Uint8Array {
  return Buffer.from(getServerEnv().SESSION_COOKIE_SECRET, "utf8");
}

/**
 * The session cookie is HttpOnly + Secure + SameSite=Lax, so it never
 * reaches JS in the browser; signing it (HS256) additionally stops a
 * tampered cookie value from being trusted if it were ever replayed
 * through a non-HttpOnly-respecting surface (e.g. a misconfigured proxy).
 * This is signing, not encryption — the token bundle is opaque to random
 * observers only because the cookie itself is HttpOnly/TLS-only, not
 * because the JWT payload is confidential. A production hardening pass
 * should switch to JWE (encrypted) if the cookie ever needs to cross a
 * boundary this repo doesn't control.
 */
export async function createSessionCookieValue(tokens: CognitoTokenResponse): Promise<string> {
  const payload: SessionPayload = {
    accessToken: tokens.access_token,
    idToken: tokens.id_token,
    refreshToken: tokens.refresh_token,
  };
  return new SignJWT({ ...payload })
    .setProtectedHeader({ alg: "HS256" })
    .setIssuedAt()
    .setExpirationTime(`${tokens.expires_in}s`)
    .sign(secretKey());
}

export async function verifySessionCookieValue(value: string): Promise<SessionPayload | null> {
  try {
    const { payload } = await jwtVerify(value, secretKey());
    if (typeof payload.accessToken !== "string" || typeof payload.idToken !== "string") {
      return null;
    }
    return {
      accessToken: payload.accessToken,
      idToken: payload.idToken,
      refreshToken: typeof payload.refreshToken === "string" ? payload.refreshToken : undefined,
    };
  } catch {
    // Expired, malformed, or signed with a different secret — treat as
    // unauthenticated rather than surfacing a 500; AuthGate's redirect-to-
    // login handles the rest.
    return null;
  }
}

export function generateCsrfToken(): string {
  return randomBytes(32).toString("hex");
}

export const SESSION_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 12;
