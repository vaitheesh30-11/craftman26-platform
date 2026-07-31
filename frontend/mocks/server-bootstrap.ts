/**
 * Imported once (top of `app/api/proxy/[...path]/route.ts`) so the Next.js
 * Node server itself intercepts outbound fetches to `BACKEND_ORIGIN`
 * during local dev, per phase-00 §6: "`pnpm dev` runs with MSW enabled by
 * default ... unless `NEXT_PUBLIC_USE_LIVE_BACKEND=true`." Module-level
 * side effect guarded by a flag because Next.js route modules can be
 * re-evaluated across hot reloads in dev.
 */
import { server } from "@/mocks/server";

declare global {
  // eslint-disable-next-line no-var
  var __sentinelMswStarted: boolean | undefined;
}

const shouldMock =
  process.env.NODE_ENV !== "production" && process.env.NEXT_PUBLIC_USE_LIVE_BACKEND !== "true";

if (shouldMock && !globalThis.__sentinelMswStarted) {
  server.listen({ onUnhandledRequest: "bypass" });
  globalThis.__sentinelMswStarted = true;
}

export { shouldMock };
