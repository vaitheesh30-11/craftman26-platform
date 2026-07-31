import { expect, test } from "@playwright/test";

// Golden flow for phase-00 §8: "Auth flow (login -> callback -> dashboard)
// works in Playwright." No real Cognito pool exists in CI, so the token
// exchange is served by MSW's mocked `/oauth2/token` handler
// (`mocks/handlers.ts`) against the zero-config dev defaults in
// `lib/env.ts` — this is the exact path `pnpm dev` boots with no `.env.local`.
test("unauthenticated visitor is redirected to login, then reaches the dashboard after callback", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/auth\/login$/);
  await expect(page.getByRole("heading", { name: "IAM Sentinel" })).toBeVisible();

  const signInHref = await page.getByRole("link", { name: "Sign in" }).getAttribute("href");
  expect(signInHref).toBeTruthy();
  const state = new URL(signInHref!).searchParams.get("state");
  expect(state).toBeTruthy();

  // Simulates Cognito's hosted-UI redirect back to our callback route with
  // an authorization code, echoing the `state` our own login page minted.
  await page.goto(`/auth/callback?code=mock-auth-code&state=${state}`);

  await expect(page).toHaveURL("/");
  await expect(page.getByRole("heading", { name: "IAM Sentinel" })).toBeVisible();
  await expect(page.getByText("F1")).toBeVisible();
});

test("callback rejects a state that doesn't match the login-minted cookie", async ({ page }) => {
  await page.goto("/auth/login");
  await page.goto("/auth/callback?code=mock-auth-code&state=not-the-real-state");
  await expect(page).toHaveURL(/\/auth\/login\?error=invalid_state$/);
});
