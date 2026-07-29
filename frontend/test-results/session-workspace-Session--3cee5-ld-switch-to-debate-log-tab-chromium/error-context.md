# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: session-workspace.spec.ts >> Session Workspace >> should switch to debate log tab
- Location: e2e\session-workspace.spec.ts:27:7

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: getByText('Agent debate')
Expected: visible
Timeout: 15000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" with timeout 15000ms
  - waiting for getByText('Agent debate')

```

```yaml
- dialog "Unhandled Runtime Error":
  - navigation:
    - button "previous" [disabled]:
      - img "previous"
    - button "next" [disabled]:
      - img "next"
    - text: 1 of 1 error Next.js (14.2.35) is outdated
    - link "(learn more)":
      - /url: https://nextjs.org/docs/messages/version-staleness
  - button "Close"
  - heading "Unhandled Runtime Error" [level=1]
  - paragraph: "TypeError: destroy is not a function"
  - heading "Call Stack" [level=2]
  - group:
    - img
    - img
    - text: React
```

# Test source

```ts
  1  | import { test, expect } from '@playwright/test';
  2  | 
  3  | test.describe('Session Workspace', () => {
  4  |   test.beforeEach(async ({ page, context }) => {
  5  |     await context.addCookies([
  6  |       { name: 'sentinel_auth_token', value: 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ0ZXN0In0.test', domain: 'localhost', path: '/' }
  7  |     ]);
  8  |     await page.goto('/sessions/1');
  9  |   });
  10 | 
  11 |   test('should load session workspace with tabs', async ({ page }) => {
  12 |     await expect(page.getByText('Human-in-the-loop workspace')).toBeVisible({ timeout: 10000 });
  13 |     await expect(page.getByRole('button', { name: 'Policy diff' })).toBeVisible();
  14 |     await expect(page.getByRole('button', { name: 'Topology map' })).toBeVisible();
  15 |     await expect(page.getByRole('button', { name: 'Debate log' })).toBeVisible();
  16 |   });
  17 | 
  18 |   test('should display execution metrics bar', async ({ page }) => {
  19 |     await expect(page.getByRole('region', { name: 'Live execution metrics' })).toBeVisible({ timeout: 10000 });
  20 |     await expect(page.getByText(/Turn \d+ \/ 3/)).toBeVisible();
  21 |   });
  22 | 
  23 |   test('should display stream status badge', async ({ page }) => {
  24 |     await expect(page.getByText(/LIVE|CONNECTING|RECONNECTING|DISCONNECTED/)).toBeVisible({ timeout: 10000 });
  25 |   });
  26 | 
  27 |   test('should switch to debate log tab', async ({ page }) => {
  28 |     await page.getByRole('button', { name: 'Debate log' }).click();
> 29 |     await expect(page.getByText('Agent debate')).toBeVisible({ timeout: 15000 });
     |                                                  ^ Error: expect(locator).toBeVisible() failed
  30 |   });
  31 | 
  32 |   test('should switch to topology map tab', async ({ page }) => {
  33 |     await page.getByRole('button', { name: 'Topology map' }).click();
  34 |     await expect(page.getByText('Cross-account trust topology')).toBeVisible({ timeout: 10000 });
  35 |   });
  36 | 
  37 |   test('should display policy diff editor', async ({ page }) => {
  38 |     await expect(page.getByText('Policy AST review')).toBeVisible({ timeout: 10000 });
  39 |     await expect(page.getByText('Enable manual override')).toBeVisible();
  40 |   });
  41 | 
  42 |   test('should display HITL control panel', async ({ page }) => {
  43 |     await expect(page.getByText('Human-in-the-loop control')).toBeVisible({ timeout: 10000 });
  44 |   });
  45 | 
  46 |   test('should display approve button in control panel', async ({ page }) => {
  47 |     await expect(page.getByRole('button', { name: /Approve/ })).toBeVisible({ timeout: 10000 });
  48 |   });
  49 | 
  50 |   test('should show session id in header', async ({ page }) => {
  51 |     await expect(page.getByText('Session 1')).toBeVisible({ timeout: 10000 });
  52 |   });
  53 | });
```