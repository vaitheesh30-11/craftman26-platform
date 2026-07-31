/**
 * Called once from `instrumentation.ts`'s `register()` hook, which runs at
 * server boot before Next.js has handled its first request. This timing
 * matters: Next's own `patch-fetch.js` reassigns `globalThis.fetch` to a
 * per-request wrapper (for its Data Cache) the moment request handling
 * starts, and if MSW's `server.listen()` patch happens AFTER that point
 * (e.g. from a module-load side effect inside the route handler itself,
 * the original approach), Next's per-request repatch clobbers it on
 * every request after the first -- every outbound fetch then falls
 * through to a real, unmocked network call and fails with ECONNREFUSED
 * against the (nonexistent) local backend. Confirmed by driving the app
 * with Playwright: /findings, /decisions, /operations, /reports, and
 * /chat all 500'd on their first data fetch before this fix.
 *
 * `server.listen()` must only be called ONCE per process -- msw >=2.15
 * throws ("cannot configure an already enabled network") on a second
 * call, unlike 2.4.10 which silently no-op'd; hence the module-level
 * guard rather than re-arming per request.
 */
import { server } from "@/mocks/server";

declare global {
  // eslint-disable-next-line no-var
  var __sentinelMswStarted: boolean | undefined;
}

const shouldMock =
  process.env.NODE_ENV !== "production" && process.env.NEXT_PUBLIC_USE_LIVE_BACKEND !== "true";

export function ensureMockServerListening(): boolean {
  if (shouldMock && !globalThis.__sentinelMswStarted) {
    server.listen({ onUnhandledRequest: "bypass" });
    globalThis.__sentinelMswStarted = true;
  }
  return shouldMock;
}

export { shouldMock };
