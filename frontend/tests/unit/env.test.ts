import { describe, expect, it, vi } from "vitest";

describe("env defaults", () => {
  it("boots with zero-config dev defaults (phase-00 §6: pnpm dev with no .env.local)", async () => {
    vi.resetModules();
    const { getPublicEnv, getServerEnv } = await import("@/lib/env");
    expect(getPublicEnv().NEXT_PUBLIC_COGNITO_DOMAIN).toBe("local-dev.auth.invalid");
    expect(getPublicEnv().NEXT_PUBLIC_USE_LIVE_BACKEND).toBe(false);
    expect(getServerEnv().SESSION_COOKIE_SECRET.length).toBeGreaterThanOrEqual(32);
  });

  it("rejects a session secret shorter than 32 bytes", async () => {
    vi.resetModules();
    vi.stubEnv("SESSION_COOKIE_SECRET", "too-short");
    const { getServerEnv } = await import("@/lib/env");
    expect(() => getServerEnv()).toThrow(/SESSION_COOKIE_SECRET/);
  });
});
