import { z } from "zod";

// Fails fast (at import time, i.e. at build/boot) rather than surfacing as
// a runtime `undefined` deep inside an OAuth redirect — matches phase-00
// §9's "Cognito hosted UI CORS misconfig" risk: catch the misconfig at
// build, not in a user's browser.
// Defaults below are deliberately non-functional placeholders: they let
// `pnpm dev`/`pnpm build` boot with zero `.env.local` (phase-00 §8's
// "`pnpm dev` boots with MSW" criterion, graded with no local secrets
// present) while still failing loudly — a 400 from Cognito, not a crash —
// if someone actually clicks through to the real hosted UI without
// configuring a real pool.
const publicEnvSchema = z.object({
  NEXT_PUBLIC_COGNITO_POOL_ID: z.string().min(1).default("local-dev-pool-id"),
  NEXT_PUBLIC_COGNITO_CLIENT_ID: z.string().min(1).default("local-dev-client-id"),
  // Full hosted-UI domain host, e.g.
  // "iam-sentinel-dev-123456.auth.us-east-1.amazoncognito.com" — aws-infra's
  // ApiStack publishes only the domain *prefix* to
  // `/sentinel/{stage}/cognito/domain`; whichever deploy step wires SSM
  // params into this env var must compose the region suffix.
  NEXT_PUBLIC_COGNITO_DOMAIN: z.string().min(1).default("local-dev.auth.invalid"),
  NEXT_PUBLIC_APP_ORIGIN: z.string().url().default("http://localhost:3000"),
  // aws-infra publishes the real value to `/sentinel/{stage}/api/websocket/url`
  // (see ADR 0022) -- wiring that SSM param into a build-time env var is a
  // deploy-pipeline concern, not this repo's frontend code.
  NEXT_PUBLIC_WS_URL: z.string().url().default("ws://localhost:8081/dev"),
  NEXT_PUBLIC_USE_LIVE_BACKEND: z
    .enum(["true", "false"])
    .default("false")
    .transform((v) => v === "true"),
});

const serverEnvSchema = z.object({
  // Origin of the FastAPI-on-Lambda backend (aws-infra `/sentinel/{stage}/api/url`).
  // Server-only: never exposed to the browser bundle (phase-00 §9 risk 2).
  BACKEND_ORIGIN: z.string().url().default("http://localhost:8000"),
  SESSION_COOKIE_SECRET: z
    .string()
    .min(32, "SESSION_COOKIE_SECRET must be >= 32 bytes; used to sign the CSRF cookie pair")
    .default("dev-only-insecure-secret-do-not-use-in-prod-xxxxxx"),
});

type PublicEnv = z.infer<typeof publicEnvSchema>;
type ServerEnv = z.infer<typeof serverEnvSchema>;

let cachedPublicEnv: PublicEnv | undefined;
let cachedServerEnv: ServerEnv | undefined;

export function getPublicEnv(): PublicEnv {
  if (!cachedPublicEnv) {
    cachedPublicEnv = publicEnvSchema.parse({
      NEXT_PUBLIC_COGNITO_POOL_ID: process.env.NEXT_PUBLIC_COGNITO_POOL_ID,
      NEXT_PUBLIC_COGNITO_CLIENT_ID: process.env.NEXT_PUBLIC_COGNITO_CLIENT_ID,
      NEXT_PUBLIC_COGNITO_DOMAIN: process.env.NEXT_PUBLIC_COGNITO_DOMAIN,
      NEXT_PUBLIC_APP_ORIGIN: process.env.NEXT_PUBLIC_APP_ORIGIN,
      NEXT_PUBLIC_WS_URL: process.env.NEXT_PUBLIC_WS_URL,
      NEXT_PUBLIC_USE_LIVE_BACKEND: process.env.NEXT_PUBLIC_USE_LIVE_BACKEND,
    });
  }
  return cachedPublicEnv;
}

/** Node-runtime only (BFF proxy / auth route handlers). Never import from a Client Component. */
export function getServerEnv(): ServerEnv {
  if (!cachedServerEnv) {
    cachedServerEnv = serverEnvSchema.parse({
      BACKEND_ORIGIN: process.env.BACKEND_ORIGIN,
      SESSION_COOKIE_SECRET: process.env.SESSION_COOKIE_SECRET,
    });
  }
  return cachedServerEnv;
}
