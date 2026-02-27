import { test, expect } from '@playwright/test';

/**
 * Account data/privacy page E2E tests.
 *
 * Tests viewing retention info, requesting export, and session management.
 * API calls mocked via page.route().
 */

test.describe('Account Data', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/api/v1/auth/me', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          data: { id: 1, email: 'driver@example.com', display_name: 'Driver', plan_tier: 'racer' },
        }),
      });
    });

    await page.route('**/api/v1/me', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ok: true, data: { entitlements: { plan_tier: 'racer' } } }),
      });
    });
  });

  test('data page renders', async ({ page }) => {
    await page.goto('/app/account/data');
    await expect(page.getByText(/data|privacy/i)).toBeVisible();
  });

  test('shows retention information', async ({ page }) => {
    await page.goto('/app/account/data');
    await expect(page.getByText(/retention|day/i)).toBeVisible();
  });

  test('has export data section', async ({ page }) => {
    await page.goto('/app/account/data');
    await expect(page.getByText(/export/i)).toBeVisible();
  });

  test('has delete account section', async ({ page }) => {
    await page.goto('/app/account/data');
    await expect(page.getByText(/delete/i)).toBeVisible();
  });
});
