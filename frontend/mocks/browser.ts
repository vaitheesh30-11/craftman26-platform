import { setupWorker } from "msw/browser";

import { handlers } from "@/mocks/handlers";

// Not started by any app code today (the BFF proxy pattern means the
// browser never calls the backend directly — see `mocks/server-
// bootstrap.ts`). Kept so a future phase with a genuine direct-from-
// browser call (e.g. WebSocket streaming, phase-01) has the worker ready
// to wire into `app/layout.tsx` without re-deriving handler wiring.
export const worker = setupWorker(...handlers);
