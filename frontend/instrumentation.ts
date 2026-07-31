/**
 * Runs once at server boot, before Next.js starts handling any request --
 * the one point where MSW's `server.listen()` patch of `globalThis.fetch`
 * is guaranteed to survive, rather than being immediately overwritten by
 * Next's own per-request fetch patch (`next/dist/server/lib/patch-fetch.js`)
 * the moment the first request comes in. See `mocks/server-bootstrap.ts`
 * for the fuller account of why this was needed.
 */
export async function register(): Promise<void> {
  if (process.env.NEXT_RUNTIME === "nodejs") {
    const { ensureMockServerListening } = await import("@/mocks/server-bootstrap");
    ensureMockServerListening();
  }
}
