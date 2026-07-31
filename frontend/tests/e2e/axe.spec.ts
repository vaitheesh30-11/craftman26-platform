import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

// phase-00 §8: "axe-core scan clean on layout and login pages." "Clean"
// is scoped to zero serious/critical violations (per EXECUTION_PLAN.txt
// §7's "axe-core zero serious violations"), not zero violations of every
// severity — moderate/minor rules (e.g. landmark-structure heuristics on a
// deliberately minimal phase-00 shell) are tracked but not gating.
test("login page has no serious or critical accessibility violations", async ({ page }) => {
  await page.goto("/auth/login");
  const results = await new AxeBuilder({ page }).analyze();
  const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(serious, JSON.stringify(serious, null, 2)).toEqual([]);
});

test("authenticated dashboard layout has no serious or critical accessibility violations", async ({ page }) => {
  await page.goto("/auth/login");
  const signInHref = await page.getByRole("link", { name: "Sign in" }).getAttribute("href");
  const state = new URL(signInHref!).searchParams.get("state");
  await page.goto(`/auth/callback?code=mock-auth-code&state=${state}`);
  await expect(page).toHaveURL("/");

  const results = await new AxeBuilder({ page }).analyze();
  const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(serious, JSON.stringify(serious, null, 2)).toEqual([]);
});
