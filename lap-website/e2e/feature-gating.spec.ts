import { test, expect } from '@playwright/test';

/**
 * Feature gating E2E tests.
 *
 * Tests that demo users see upgrade banners and paid users see features.
 * API calls mocked via page.route().
 */

test.describe('Feature Gating - Demo User', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/api/v1/auth/me', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          data: { id: 1, email: 'demo@example.com', display_name: 'Demo User', plan_tier: 'demo' },
        }),
      });
    });

    await page.route('**/api/v1/me', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          data: {
            entitlements: {
              plan_tier: 'demo',
              comparison_progress: false,
              api_access: false,
              reports_per_month: 1,
            },
          },
        }),
      });
    });
  });

  test('demo user sees upgrade prompt on compare page', async ({ page }) => {
    await page.goto('/app/compare');
    // Should see upgrade banner or redirect
    const upgradeText = page.getByText(/upgrade|premium|unlock/i);
    const redirected = page.url().includes('pricing') || page.url().includes('upgrade');
    // Either shows upgrade text or redirects
    expect(await upgradeText.isVisible().catch(() => false) || redirected).toBeTruthy();
  });
});

test.describe('Feature Gating - Racer User', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/api/v1/auth/me', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          data: { id: 1, email: 'racer@example.com', display_name: 'Racer', plan_tier: 'racer' },
        }),
      });
    });

    await page.route('**/api/v1/me', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          data: {
            entitlements: {
              plan_tier: 'racer',
              coaching_drills: true,
              pdf_reports: true,
              reports_per_month: 10,
            },
          },
        }),
      });
    });
  });

  test('racer user can access dashboard', async ({ page }) => {
    await page.goto('/app/dashboard');
    await expect(page.getByText(/dashboard/i)).toBeVisible();
  });
});
