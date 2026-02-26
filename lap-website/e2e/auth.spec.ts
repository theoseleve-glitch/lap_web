import { test, expect } from '@playwright/test';

/**
 * Authentication flow E2E tests.
 *
 * The auth pages live under the (auth) route group:
 *   /login    - LoginPage: email + password form, "Sign In" heading
 *   /register - RegisterPage: display name + email + password + confirm, "Create Account" heading
 *
 * The login form calls POST /api/v1/auth/login and on success redirects to /app/dashboard.
 * The register form calls POST /api/v1/auth/register and on success redirects to /login?registered=true.
 *
 * We mock the API responses via page.route() since no backend is running.
 */
test.describe('Registration flow', () => {
  test('register page renders form with all fields', async ({ page }) => {
    await page.goto('/register');

    // Heading
    await expect(page.getByRole('heading', { name: 'Create Account' })).toBeVisible();

    // All four form fields are present via their label text
    await expect(page.getByText('Display Name')).toBeVisible();
    await expect(page.getByText('Email')).toBeVisible();
    await expect(page.getByText('Password', { exact: false })).toBeVisible();
    await expect(page.getByText('Confirm Password')).toBeVisible();

    // Submit button
    await expect(page.getByRole('button', { name: 'Create Account' })).toBeVisible();

    // Link to login
    await expect(page.getByRole('link', { name: 'Sign in' })).toBeVisible();
  });

  test('register form submits and redirects to login', async ({ page }) => {
    // Mock the register API endpoint
    await page.route('**/api/v1/auth/register', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          data: {
            user: { id: 1, email: 'test@example.com', display_name: 'Test Driver' },
          },
          meta: { request_id: 'test-req-1' },
        }),
      });
    });

    await page.goto('/register');

    // Fill form fields using placeholder text as locators
    await page.getByPlaceholder('Your name').fill('Test Driver');
    await page.getByPlaceholder('driver@example.com').fill('test@example.com');
    await page.getByPlaceholder('Minimum 8 characters').fill('password123');
    await page.getByPlaceholder('Re-enter password').fill('password123');

    // Submit
    await page.getByRole('button', { name: 'Create Account' }).click();

    // Should redirect to /login with registered=true query param
    await expect(page).toHaveURL(/\/login\?registered=true/);
  });
});

test.describe('Login flow', () => {
  test('login page renders form with email and password fields', async ({ page }) => {
    await page.goto('/login');

    // Heading
    await expect(page.getByRole('heading', { name: 'Sign In' })).toBeVisible();

    // Form fields
    await expect(page.getByText('Email')).toBeVisible();
    await expect(page.getByText('Password')).toBeVisible();

    // Submit button
    await expect(page.getByRole('button', { name: 'Sign In' })).toBeVisible();

    // Link to register
    await expect(page.getByRole('link', { name: 'Create one' })).toBeVisible();
  });

  test('login form submits and redirects to dashboard', async ({ page }) => {
    // Mock the login API endpoint
    await page.route('**/api/v1/auth/login', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          data: {
            access_token: 'test-jwt-token',
            refresh_token: 'test-refresh-token',
            user: { id: 1, email: 'driver@example.com', display_name: 'Test Driver' },
          },
          meta: { request_id: 'test-req-2' },
        }),
      });
    });

    // Also mock the dashboard stats API that fires after redirect
    await page.route('**/api/v1/dashboard/stats', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          data: {
            total_sessions: 12,
            pb_time: 62.345,
            avg_score: 78.5,
            total_drivers: 3,
            recent_scores: [],
            recent_times: [],
            recent_sessions: [],
          },
          meta: { request_id: 'test-req-3' },
        }),
      });
    });

    await page.goto('/login');

    // Fill credentials
    await page.getByPlaceholder('driver@example.com').fill('driver@example.com');
    await page.getByPlaceholder(/••••••••/).fill('password123');

    // Submit
    await page.getByRole('button', { name: 'Sign In' }).click();

    // useAuth.login() calls router.push('/app/dashboard') on success
    await expect(page).toHaveURL(/\/app\/dashboard/);
  });
});
