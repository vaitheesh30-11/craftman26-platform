import { test, expect } from '@playwright/test';

test.describe('Sentinel-IQ Dashboard', () => {
  test('should display header and brand', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText('Sentinel-IQ').first()).toBeVisible();
    await expect(page.getByText('Governance command center')).toBeVisible();
  });

  test('should show session data after loading', async ({ page }) => {
    await page.goto('/');
    // Wait for the session table data to appear (React Query resolves mock data)
    await expect(page.getByRole('link', { name: 'ses-7f43' })).toBeVisible({ timeout: 20000 });
    await expect(page.getByRole('link', { name: 'ses-1ac9' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'ses-8d22' })).toBeVisible();
  });

  test('should display status badges', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('link', { name: 'ses-7f43' })).toBeVisible({ timeout: 20000 });
    await expect(page.getByText('Awaiting HITL').first()).toBeVisible();
    await expect(page.getByText('Synthesizing').first()).toBeVisible();
    await expect(page.getByText('Committed').first()).toBeVisible();
  });

  test('should display stats cards', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('link', { name: 'ses-7f43' })).toBeVisible({ timeout: 20000 });
    await expect(page.getByText('Total sessions')).toBeVisible();
    await expect(page.getByText('Awaiting review')).toBeVisible();
    await expect(page.getByText('Avg blast radius')).toBeVisible();
  });

  test('should navigate to session workspace with auth cookie', async ({ page, context }) => {
    await context.addCookies([
      { name: 'sentinel_auth_token', value: 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ0ZXN0In0.test', domain: 'localhost', path: '/' }
    ]);
    await page.goto('/');
    const link = page.getByRole('link', { name: 'ses-7f43' });
    await expect(link).toBeVisible({ timeout: 20000 });
    await link.click();
    await page.waitForURL(/\/sessions\/1/);
    await expect(page.getByText('Human-in-the-loop workspace')).toBeVisible({ timeout: 15000 });
  });
});