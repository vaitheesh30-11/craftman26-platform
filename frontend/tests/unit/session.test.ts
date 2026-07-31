// @vitest-environment node
//
// `lib/session.ts` signs via `jose`, which memoizes its own module-level
// `TextEncoder`/`TextDecoder` at import time (see
// `jose/dist/*/lib/buffer_utils.js`). Vitest's default jsdom environment
// installs jsdom's own `TextEncoder` as the global before that import
// runs, so jose's internal encoder and its `instanceof Uint8Array` checks
// end up split across two different realms and every sign() throws
// "payload must be an instance of Uint8Array" — nothing to do with this
// module's actual logic. This file needs no DOM, so run it under plain
// Node instead of chasing jsdom/jose interop.
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.stubEnv("SESSION_COOKIE_SECRET", "unit-test-secret-at-least-32-bytes-long-000");
vi.stubEnv("BACKEND_ORIGIN", "http://localhost:8000");

const { createSessionCookieValue, verifySessionCookieValue } = await import("@/lib/session");

describe("session cookie codec", () => {
  beforeEach(() => {
    vi.useRealTimers();
  });

  it("round-trips a signed session payload", async () => {
    const value = await createSessionCookieValue({
      access_token: "at",
      id_token: "it",
      refresh_token: "rt",
      token_type: "Bearer",
      expires_in: 3600,
    });

    const payload = await verifySessionCookieValue(value);
    expect(payload).toEqual({ accessToken: "at", idToken: "it", refreshToken: "rt" });
  });

  it("returns null for a tampered cookie value", async () => {
    const value = await createSessionCookieValue({
      access_token: "at",
      id_token: "it",
      token_type: "Bearer",
      expires_in: 3600,
    });
    const tampered = value.slice(0, -4) + "abcd";
    expect(await verifySessionCookieValue(tampered)).toBeNull();
  });

  it("returns null for garbage input", async () => {
    expect(await verifySessionCookieValue("not-a-jwt")).toBeNull();
  });
});
