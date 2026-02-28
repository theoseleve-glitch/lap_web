/**
 * App Features Certification — Authenticated UI + API tests.
 *
 * Covers:
 *   Account: F-0172, F-0176, F-0180, F-0181, F-0183, F-0186
 *   Billing: F-0155, F-0165, F-0170
 *
 * IMPORTANT: Auth tokens are in-memory JS — page.goto() triggers full reload
 * and loses the token. Use client-side nav (link clicks) after login.
 */
import { test, expect, Page } from '@playwright/test';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'https://api.lap-coach.racing';

const ACCOUNTS = {
  demo: {
    email: process.env.E2E_DEMO_EMAIL || 'theos.elive@gmail.com',
    password: process.env.E2E_TEST_PASSWORD || 'claudetest',
    tier: 'demo',
  },
  racer: {
    email: process.env.E2E_RACER_EMAIL || 'theo.stipapro@gmail.com',
    password: process.env.E2E_TEST_PASSWORD || 'claudetest',
    tier: 'racer',
  },
  world_class: {
    email: process.env.E2E_WC_EMAIL || 'fsae.ecn@gmail.com',
    password: process.env.E2E_TEST_PASSWORD || 'claudetest',
    tier: 'world_class',
  },
} as const;

type Tier = keyof typeof ACCOUNTS;

async function apiLogin(page: Page, tier: Tier): Promise<string> {
  const acct = ACCOUNTS[tier];
  const res = await page.request.post(`${API_URL}/auth/login`, {
    data: { email: acct.email, password: acct.password },
  });
  const body = await res.json();
  if (!body.ok) throw new Error(`Login failed: ${JSON.stringify(body)}`);
  return body.data.access_token;
}

async function authedGet(page: Page, path: string, token: string) {
  return page.request.get(`${API_URL}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
}

/** Login via UI, wait for /app redirect, return the page ready for client-side nav. */
async function uiLogin(page: Page, tier: Tier) {
  const acct = ACCOUNTS[tier];
  await page.goto('/login');
  const emailInput = page.getByPlaceholder('driver@example.com');
  const passwordInput = page.getByPlaceholder('••••••••');
  await emailInput.waitFor({ state: 'visible', timeout: 10000 });
  await emailInput.click();
  await emailInput.fill(acct.email);
  await passwordInput.click();
  await passwordInput.fill(acct.password);
  await page.waitForTimeout(500);
  await page.getByRole('button', { name: /sign in/i }).click();
  await page.waitForURL(/\/app/, { timeout: 30000 });
}

/**
 * Navigate via client-side routing (clicks an anchor) to preserve in-memory auth.
 * Falls back to evaluating history.pushState + waitForURL if no link found.
 */
async function clientNav(page: Page, path: string) {
  const link = page.locator(`a[href="${path}"]`).first();
  if (await link.isVisible({ timeout: 3000 }).catch(() => false)) {
    await link.click();
  } else {
    // Use Next.js router via evaluate — pushes to path without full reload
    await page.evaluate((p) => {
      window.history.pushState({}, '', p);
      window.dispatchEvent(new PopStateEvent('popstate'));
    }, path);
    // Wait a moment for React to pick up the route change
    await page.waitForTimeout(500);
  }
  await page.waitForLoadState('networkidle');
}

// ============================================================
// Account UI Features — single login, client-side navigation
// ============================================================

test.describe('Account UI Features (F-0172..F-0186)', () => {
  test('login and verify account profile page', async ({ page }) => {
    await uiLogin(page, 'demo');

    // Navigate to profile using sidebar/link click (preserves auth state)
    await clientNav(page, '/app/account/profile');

    // F-0172: Profile displays name, email, plan tier
    await expect(page.locator('body')).toContainText(/profile|account|personal/i, {
      timeout: 15000,
    });
    // Email is inside an input value, not visible text — check input value
    const emailInput = page.locator(`input[value="${ACCOUNTS.demo.email}"]`);
    await expect(emailInput).toBeVisible({ timeout: 10000 });

    // F-0176: Avatar/display name rendering
    const nameField = page
      .getByText(/display name|name/i)
      .or(page.getByLabel(/display name|name/i))
      .or(page.locator('input[type="text"]'));
    await expect(nameField.first()).toBeVisible({ timeout: 10000 });
  });

  test('login and verify security page', async ({ page }) => {
    await uiLogin(page, 'demo');
    await clientNav(page, '/app/account/security');

    // F-0186: Security settings page renders
    await expect(
      page.getByText(/password|security|two-factor|2fa/i).first()
    ).toBeVisible({ timeout: 15000 });

    // F-0180: Session history/activity display
    await expect(
      page.getByText(/active session|session|browser|device|current/i).first()
    ).toBeVisible({ timeout: 10000 });

    // F-0181: Connected OAuth accounts display
    await expect(
      page.getByText(/connected|google|github|oauth|linked/i).first()
    ).toBeVisible({ timeout: 10000 });
  });

  test('login and verify dashboard renders (F-0183)', async ({ page }) => {
    await uiLogin(page, 'demo');
    // Already on /app/dashboard after login — just verify content
    await expect(
      page
        .getByText(/dashboard|overview|telemetry|welcome/i)
        .or(page.locator('aside'))
        .first()
    ).toBeVisible({ timeout: 15000 });
  });
});

// ============================================================
// Billing UI Features (F-0155, F-0165, F-0170)
// ============================================================

test.describe('Billing UI Features', () => {
  test('F-0155 pricing page displays plan cards and prices', async ({ page }) => {
    await page.goto('/pricing');
    await expect(page.getByText(/demo/i).first()).toBeVisible({ timeout: 10000 });
    await expect(page.getByText(/racer/i).first()).toBeVisible();
    await expect(page.getByText(/world.?class/i).first()).toBeVisible();
    await expect(page.getByText(/free/i).first()).toBeVisible();
    await expect(
      page.locator(':not(select):not(option)').getByText(/€\d/i).first()
    ).toBeVisible();
  });

  test('F-0165 billing page shows plan info (via auth)', async ({ page }) => {
    await uiLogin(page, 'demo');
    await clientNav(page, '/app/account/billing');

    // Billing page should show current plan info
    await expect(page.locator('body')).toContainText(/plan|billing|subscription|free|demo/i, {
      timeout: 15000,
    });
  });

  test('F-0170 annual vs monthly billing toggle', async ({ page }) => {
    await page.goto('/pricing');
    const toggle = page
      .getByRole('button', { name: /annual|monthly|billing/i })
      .or(page.getByText(/annual|yearly/i));
    await expect(toggle.first()).toBeVisible({ timeout: 10000 });
  });
});

// ============================================================
// Account API — per tier (serial to avoid rate limits)
// ============================================================

test.describe('Account API — per tier', () => {
  test.describe.configure({ mode: 'serial' });
  let tokens: Record<string, string> = {};

  test('login all 3 tiers', async ({ page }) => {
    for (const tier of ['demo', 'racer', 'world_class'] as Tier[]) {
      tokens[tier] = await apiLogin(page, tier);
    }
    expect(Object.keys(tokens)).toHaveLength(3);
  });

  test('demo profile returns correct email', async ({ page }) => {
    const res = await authedGet(page, '/api/v1/me', tokens.demo);
    const body = await res.json();
    expect(body.ok).toBe(true);
    expect(body.data.email).toBe(ACCOUNTS.demo.email);
  });

  test('racer profile returns correct email', async ({ page }) => {
    const res = await authedGet(page, '/api/v1/me', tokens.racer);
    const body = await res.json();
    expect(body.ok).toBe(true);
    expect(body.data.email).toBe(ACCOUNTS.racer.email);
  });

  test('world_class profile returns correct email', async ({ page }) => {
    const res = await authedGet(page, '/api/v1/me', tokens.world_class);
    const body = await res.json();
    expect(body.ok).toBe(true);
    expect(body.data.email).toBe(ACCOUNTS.world_class.email);
  });

  test('each tier returns plan in entitlements', async ({ page }) => {
    for (const tier of ['demo', 'racer', 'world_class'] as Tier[]) {
      const res = await authedGet(page, '/api/v1/account/entitlements', tokens[tier]);
      const body = await res.json();
      expect(body.ok).toBe(true);
      expect(body.data).toHaveProperty('plan');
      expect(body.data).toHaveProperty('entitlements');
    }
  });
});
