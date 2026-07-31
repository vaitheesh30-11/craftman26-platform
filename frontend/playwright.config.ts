import { defineConfig, devices } from "@playwright/test";

const PORT = 3100;

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: `http://localhost:${PORT}`,
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  // Dev mode, not `build && start`: phase-00 §6's MSW-by-default behavior
  // (`mocks/server-bootstrap.ts`) is gated on `NODE_ENV !== "production"`,
  // and the golden auth-flow spec needs MSW's mocked Cognito token endpoint
  // (see `mocks/handlers.ts`) since no real Cognito pool exists in CI.
  // `pnpm build`'s own success is verified separately by the toolchain run,
  // not by this suite.
  webServer: {
    command: `pnpm dev -- -p ${PORT}`,
    url: `http://localhost:${PORT}`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
