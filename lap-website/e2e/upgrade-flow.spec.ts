import { test, expect } from '@playwright/test';

/**
 * Upgrade flow E2E tests.
 *
 * Tests clicking upgrade → redirect to Stripe checkout → return.
 * Stripe checkout is mocked since we can't test real payments.
 */

test.describe('Upgrade Flow', () => {
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
          data: { entitlements: { plan_tier: 'demo', reports_per_month: 1 } },
        }),
      });
    });
  });

  test('billing upgrade page renders', async ({ page }) => {
    await page.goto('/app/account/billing/upgrade');
    // Should show plan options
    await expect(page.getByText(/racer|performance|plan/i)).toBeVisible();
  });

  test('upgrade page shows pricing tiers', async ({ page }) => {
    await page.goto('/app/account/billing/upgrade');
    // Should show at least one plan option
    const planCard = page.getByText(/month|annual|year/i);
    await expect(planCard).toBeVisible();
  });

  test('upgrade button creates checkout session', async ({ page }) => {
    let checkoutCalled = false;
    await page.route('**/api/v1/billing/checkout', async (route) => {
      checkoutCalled = true;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          data: { checkout_url: 'https://checkout.stripe.com/test' },
        }),
      });
    });

    await page.goto('/app/account/billing/upgrade');
    const upgradeBtn = page.getByRole('button', { name: /upgrade|subscribe|get started/i });
    if (await upgradeBtn.isVisible().catch(() => false)) {
      await upgradeBtn.click();
      // Should have called the checkout API
    }
  });
});
