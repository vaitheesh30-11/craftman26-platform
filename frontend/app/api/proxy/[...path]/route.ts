/**
 * BFF proxy (phase-00 §4). Runs on the Node.js runtime (not Edge — needs
 * `node:crypto` for correlation IDs and full `Response.body` streaming
 * control). Every browser-to-backend call passes through here so the
 * bearer token never reaches client JS.
 */
import { randomUUID } from "node:crypto";

import { cookies } from "next/headers";
import { NextResponse, type NextRequest } from "next/server";

import { refreshTokens } from "@/lib/auth";
import { getServerEnv } from "@/lib/env";
import { ensureMockServerListening } from "@/mocks/server-bootstrap";
import {
  createSessionCookieValue,
  SESSION_COOKIE_MAX_AGE_SECONDS,
  SESSION_COOKIE_NAME,
  CSRF_COOKIE_NAME,
  verifySessionCookieValue,
} from "@/lib/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const MUTATING_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

function unauthenticated(correlationId: string) {
  return NextResponse.json(
    { ok: false, error: { code: "UNAUTHENTICATED", message: "No valid session.", correlation_id: correlationId } },
    { status: 401 },
  );
}

function forbiddenCsrf(correlationId: string) {
  return NextResponse.json(
    {
      ok: false,
      error: { code: "CSRF_MISMATCH", message: "Missing or invalid x-csrf-token.", correlation_id: correlationId },
    },
    { status: 403 },
  );
}

async function proxy(request: NextRequest, path: string[]): Promise<NextResponse> {
  ensureMockServerListening();
  const correlationId = request.headers.get("x-correlation-id") ?? randomUUID();
  const method = request.method.toUpperCase();

  const cookieStore = cookies();
  const sessionCookie = cookieStore.get(SESSION_COOKIE_NAME)?.value;
  if (!sessionCookie) {
    return unauthenticated(correlationId);
  }

  // Same-origin + double-submit CSRF check (phase-00 §4): the cookie is
  // JS-readable by design (double-submit pattern needs that); the session
  // cookie carrying the actual bearer token stays HttpOnly regardless.
  if (MUTATING_METHODS.has(method)) {
    const csrfCookie = cookieStore.get(CSRF_COOKIE_NAME)?.value;
    const csrfHeader = request.headers.get("x-csrf-token");
    if (!csrfCookie || !csrfHeader || csrfCookie !== csrfHeader) {
      return forbiddenCsrf(correlationId);
    }
  }

  let session = await verifySessionCookieValue(sessionCookie);
  if (!session) {
    return unauthenticated(correlationId);
  }

  const backendOrigin = getServerEnv().BACKEND_ORIGIN;
  const targetUrl = new URL(`/${path.join("/")}`, backendOrigin);
  targetUrl.search = request.nextUrl.search;

  const body = MUTATING_METHODS.has(method) ? await request.text() : undefined;

  const forward = (accessToken: string) =>
    fetch(targetUrl, {
      method,
      headers: {
        Authorization: `Bearer ${accessToken}`,
        "X-Correlation-Id": correlationId,
        ...(body ? { "Content-Type": "application/json" } : {}),
      },
      body,
      cache: "no-store",
    });

  let backendResponse = await forward(session.accessToken);
  let refreshedCookieValue: string | null = null;

  // Silent refresh on a single 401 (phase-00 §3). Only attempted once —
  // a second consecutive 401 means the refresh token itself is dead, not
  // a transient access-token expiry.
  if (backendResponse.status === 401 && session.refreshToken) {
    try {
      const refreshed = await refreshTokens(session.refreshToken);
      refreshedCookieValue = await createSessionCookieValue(refreshed);
      session = { accessToken: refreshed.access_token, idToken: refreshed.id_token, refreshToken: refreshed.refresh_token ?? session.refreshToken };
      backendResponse = await forward(session.accessToken);
    } catch {
      cookieStore.delete(SESSION_COOKIE_NAME);
      return unauthenticated(correlationId);
    }
  }

  const contentType = backendResponse.headers.get("content-type") ?? "";
  const responseInit = { status: backendResponse.status, headers: { "x-correlation-id": correlationId } };

  const response = contentType.includes("text/event-stream")
    ? new NextResponse(backendResponse.body, {
        ...responseInit,
        headers: { ...responseInit.headers, "content-type": contentType },
      })
    : NextResponse.json(await backendResponse.json(), responseInit);

  if (refreshedCookieValue) {
    response.cookies.set(SESSION_COOKIE_NAME, refreshedCookieValue, {
      httpOnly: true,
      secure: process.env.NODE_ENV === "production",
      sameSite: "lax",
      path: "/",
      maxAge: SESSION_COOKIE_MAX_AGE_SECONDS,
    });
  }

  return response;
}

export async function GET(request: NextRequest, { params }: { params: { path: string[] } }) {
  return proxy(request, params.path);
}
export async function POST(request: NextRequest, { params }: { params: { path: string[] } }) {
  return proxy(request, params.path);
}
export async function PUT(request: NextRequest, { params }: { params: { path: string[] } }) {
  return proxy(request, params.path);
}
export async function PATCH(request: NextRequest, { params }: { params: { path: string[] } }) {
  return proxy(request, params.path);
}
export async function DELETE(request: NextRequest, { params }: { params: { path: string[] } }) {
  return proxy(request, params.path);
}
