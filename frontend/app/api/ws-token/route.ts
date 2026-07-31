import { NextResponse } from "next/server";

import { getCurrentSession } from "@/lib/current-session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Same-origin-only token mint for the WebSocket handshake (ADR 0022):
 * browsers cannot attach an HttpOnly cookie's value, or any custom
 * header, to a WebSocket upgrade request, so `lib/websocket-client.ts`
 * fetches this once (credentialed, same-origin) immediately before
 * opening the socket and carries the access token in the connection URL's
 * query string instead. Returns only the short-lived access token, never
 * the refresh token, and only to the cookie's own owner.
 */
export async function GET(): Promise<NextResponse> {
  const session = await getCurrentSession();
  if (!session) {
    return NextResponse.json(
      { ok: false, error: { code: "UNAUTHENTICATED", message: "No valid session.", correlation_id: "" } },
      { status: 401 },
    );
  }
  return NextResponse.json({ ok: true, data: { token: session.accessToken } }, { headers: { "cache-control": "no-store" } });
}
