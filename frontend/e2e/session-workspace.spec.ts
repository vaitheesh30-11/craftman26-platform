import { test, expect } from '@playwright/test';

test.describe('Session Workspace', () => {
  test.beforeEach(async ({ page, context }) => {
    await context.addCookies([
      { name: 'sentinel_auth_token', value: 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ0ZXN0In0.test', domain: 'localhost', path: '/' }
    ]);
    await page.goto('/sessions/1');
  });

  test('should load session workspace with tabs', async ({ page }) => {
    await expect(page.getByText('Human-in-the-loop workspace')).toBeVisible({ timeout: 10000 });
    await expect(page.getByRole('button', { name: 'Policy diff' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Topology map' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Debate log' })).toBeVisible();
  });

  test('should display execution metrics bar', async ({ page }) => {
    await expect(page.getByRole('region', { name: 'Live execution metrics' })).toBeVisible({ timeout: 10000 });
    await expect(page.getByText(/Turn \d+ \/ 3/)).toBeVisible();
  });

  test('should display stream status badge', async ({ page }) => {
    await expect(page.getByText(/LIVE|CONNECTING|RECONNECTING|DISCONNECTED/)).toBeVisible({ timeout: 10000 });
  });

  test('should switch to debate log tab', async ({ page }) => {
    await page.getByRole('button', { name: 'Debate log' }).click();
    await page.waitForTimeout(3000);
    await expect(page.getByText('Agent debate')).toBeVisible({ timeout: 10000 });
  });

  test('should switch to topology map tab', async ({ page }) => {
    await page.getByRole('button', { name: 'Topology map' }).click();
    await expect(page.getByText('Cross-account trust topology')).toBeVisible({ timeout: 10000 });
  });

  test('should display policy diff editor', async ({ page }) => {
    await expect(page.getByText('Policy AST review')).toBeVisible({ timeout: 10000 });
    await expect(page.getByText('Enable manual override')).toBeVisible();
  });

  test('should display HITL control panel', async ({ page }) => {
    await expect(page.getByText('Human-in-the-loop control')).toBeVisible({ timeout: 10000 });
  });

  test('should display approve button in control panel', async ({ page }) => {
    await expect(page.getByRole('button', { name: /Approve/ })).toBeVisible({ timeout: 10000 });
  });

  test('should show session id in header', async ({ page }) => {
    await expect(page.getByText('Session 1')).toBeVisible({ timeout: 10000 });
  });
});