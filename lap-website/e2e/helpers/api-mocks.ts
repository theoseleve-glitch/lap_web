import { Page } from '@playwright/test';

/**
 * Mock /auth/me to simulate a logged-in user at a specific tier.
 */
export async function mockAuthMe(page: Page, tier: 'demo' | 'racer' | 'world_class') {
  // Mock user data — IDs are synthetic, emails from env or placeholders.
  const users = {
    demo: { id: 1, email: process.env.E2E_DEMO_EMAIL || 'demo@test.local', display_name: 'Demo User', plan_tier: 'demo' },
    racer: { id: 2, email: process.env.E2E_RACER_EMAIL || 'racer@test.local', display_name: 'Racer User', plan_tier: 'racer' },
    world_class: { id: 3, email: process.env.E2E_WC_EMAIL || 'wc@test.local', display_name: 'World Class User', plan_tier: 'world_class' },
  };

  await page.route('**/api/v1/auth/me', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, data: users[tier], meta: {} }),
    });
  });

  await page.route('**/api/v1/me', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, data: users[tier], meta: {} }),
    });
  });
}

/**
 * Mock entitlement snapshot for tier-gated tests.
 */
export async function mockEntitlements(page: Page, tier: 'demo' | 'racer' | 'world_class') {
  const entitlements = {
    demo: {
      plan_tier: 'demo', reports_per_month: 1, uploads_per_month: 1,
      api_access: false, comparison_enabled: false, visualization_enabled: false,
      coaching_plans_enabled: false, live_monitoring: false,
    },
    racer: {
      plan_tier: 'racer', reports_per_month: 10, uploads_per_month: 10,
      api_access: false, comparison_enabled: false, visualization_enabled: true,
      coaching_plans_enabled: true, live_monitoring: true,
    },
    world_class: {
      plan_tier: 'world_class', reports_per_month: -1, uploads_per_month: -1,
      api_access: true, comparison_enabled: true, visualization_enabled: true,
      coaching_plans_enabled: true, live_monitoring: true,
    },
  };

  await page.route('**/api/v1/account/entitlements', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, data: entitlements[tier], meta: {} }),
    });
  });
}
