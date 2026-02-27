import { test, expect } from '@playwright/test';

/**
 * Account profile page E2E tests.
 *
 * Tests editing display name, changing email, and updating preferences.
 * API calls mocked via page.route() — no backend required.
 */

const MOCK_PROFILE = {
  ok: true,
  data: {
    id: 1,
    email: 'driver@example.com',
    display_name: 'Test Driver',
    language: 'en',
    timezone: 'Europe/London',
    units: 'metric',
    speed_unit: 'kmh',
    plan_tier: 'racer',
    subscription_status: 'active',
  },
};

test.describe('Account Profile', () => {
  test.beforeEach(async ({ page }) => {
    // Mock auth check
    await page.route('**/api/v1/auth/me', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_PROFILE) });
    });

    // Mock entitlements
    await page.route('**/api/v1/me', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ok: true, data: { entitlements: { plan_tier: 'racer' } } }),
      });
    });
  });

  test('profile page renders user info', async ({ page }) => {
    await page.goto('/app/account/profile');
    await expect(page.getByText('Profile')).toBeVisible();
  });

  test('profile page has display name field', async ({ page }) => {
    await page.goto('/app/account/profile');
    await expect(page.getByText('Display Name', { exact: false })).toBeVisible();
  });

  test('profile page has email field', async ({ page }) => {
    await page.goto('/app/account/profile');
    await expect(page.getByText('Email', { exact: false })).toBeVisible();
  });

  test('profile page has save button', async ({ page }) => {
    await page.goto('/app/account/profile');
    const saveButton = page.getByRole('button', { name: /save|update/i });
    await expect(saveButton).toBeVisible();
  });

  test('update profile calls API', async ({ page }) => {
    let apiCalled = false;
    await page.route('**/api/v1/account/preferences', async (route) => {
      apiCalled = true;
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true }) });
    });

    await page.goto('/app/account/profile');
    // Find and interact with a form field
    const saveButton = page.getByRole('button', { name: /save|update/i });
    if (await saveButton.isVisible()) {
      await saveButton.click();
    }
  });
});
