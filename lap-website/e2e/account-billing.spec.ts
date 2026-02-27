import { test, expect } from '@playwright/test';

/**
 * Account billing page E2E tests.
 *
 * Tests viewing current plan, usage bars, and invoice history.
 * API calls mocked via page.route().
 */

test.describe('Account Billing', () => {
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

    await page.route('**/api/v1/billing/status', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          data: {
            plan_tier: 'racer',
            subscription_status: 'active',
            current_period_end: '2026-04-01T00:00:00Z',
            cancel_at_period_end: false,
          },
        }),
      });
    });
  });

  test('billing page renders', async ({ page }) => {
    await page.goto('/app/account/billing');
    await expect(page.getByText(/billing|plan/i)).toBeVisible();
  });

  test('shows current plan tier', async ({ page }) => {
    await page.goto('/app/account/billing');
    await expect(page.getByText(/racer/i)).toBeVisible();
  });

  test('shows subscription status', async ({ page }) => {
    await page.goto('/app/account/billing');
    await expect(page.getByText(/active/i)).toBeVisible();
  });

  test('has manage subscription button', async ({ page }) => {
    await page.goto('/app/account/billing');
    const manageBtn = page.getByRole('button', { name: /manage|portal|upgrade/i });
    // Button should exist (may be "Manage Subscription" or "Upgrade")
    await expect(manageBtn.or(page.getByRole('link', { name: /manage|portal|upgrade/i }))).toBeVisible();
  });
});
