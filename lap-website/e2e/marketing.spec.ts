import { test, expect } from '@playwright/test';

/**
 * Marketing page E2E tests.
 *
 * The homepage (/) renders a sequence of "room" components inside a
 * ChromeLayout. The first visible element is the StartGrid which shows
 * the monument text "EVERY LAP / HAS A SECRET". The marketing layout
 * includes navigation with a login link.
 */
test.describe('Marketing pages', () => {
  test('homepage loads and shows hero monument text', async ({ page }) => {
    await page.goto('/');

    // The StartGrid component renders monument text from the copy data.
    // Default variant shows "EVERY LAP" and "HAS A SECRET".
    await expect(page.getByText('EVERY LAP')).toBeVisible();
    await expect(page.getByText('HAS A SECRET')).toBeVisible();

    // The main element wraps all room components
    await expect(page.locator('main')).toBeVisible();
  });

  test('homepage login link navigates to /login', async ({ page }) => {
    await page.goto('/');

    // The ChromeLayout renders a top navigation bar with a login link.
    // Look for a link that navigates to /login.
    const loginLink = page.getByRole('link', { name: /sign in|log in|login/i });
    await expect(loginLink).toBeVisible();
    await loginLink.click();

    await expect(page).toHaveURL(/\/login/);
  });

  test('pricing page loads', async ({ page }) => {
    await page.goto('/pricing');

    // The pricing page should be accessible and render content
    await expect(page.locator('main')).toBeVisible();
  });

  test('product page loads', async ({ page }) => {
    await page.goto('/product');

    await expect(page.locator('main')).toBeVisible();
  });
});
