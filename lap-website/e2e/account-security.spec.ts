import { test, expect } from '@playwright/test';

/**
 * Account security page E2E tests.
 *
 * Tests password change form, 2FA setup section, and session management.
 * API calls mocked via page.route().
 */

test.describe('Account Security', () => {
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

  test('security page renders', async ({ page }) => {
    await page.goto('/app/account/security');
    await expect(page.getByText('Security')).toBeVisible();
  });

  test('has password change section', async ({ page }) => {
    await page.goto('/app/account/security');
    await expect(page.getByText(/password/i)).toBeVisible();
  });

  test('has 2FA section', async ({ page }) => {
    await page.goto('/app/account/security');
    await expect(page.getByText(/two.factor|2fa|authenticator/i)).toBeVisible();
  });

  test('has session management section', async ({ page }) => {
    await page.goto('/app/account/security');
    await expect(page.getByText(/session|device/i)).toBeVisible();
  });
});
