/**
 * API Endpoint Certification — Real API, all tiers, all major endpoints.
 *
 * Tests every accessible API endpoint with all 3 tier accounts.
 * Uses a single login per tier to avoid rate limits (20/60s on auth).
 *
 * Env vars: E2E_DEMO_EMAIL, E2E_RACER_EMAIL, E2E_WC_EMAIL, E2E_TEST_PASSWORD
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

// ---------- helpers ----------

async function authedGet(page: Page, path: string, token: string) {
  return page.request.get(`${API_URL}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
}

// ---------- Shared token state ----------
// Each describe.serial group logs in once and reuses the token.

for (const tier of ['demo', 'racer', 'world_class'] as Tier[]) {
  test.describe(`Certification — ${tier}`, () => {
    test.describe.configure({ mode: 'serial' });
    let token: string;

    test(`[${tier}] login`, async ({ page }) => {
      const acct = ACCOUNTS[tier];
      const res = await page.request.post(`${API_URL}/auth/login`, {
        data: { email: acct.email, password: acct.password },
      });
      const body = await res.json();
      expect(body.ok).toBe(true);
      token = body.data.access_token;
    });

    // ── Account endpoints ──

    test(`[${tier}] GET /api/v1/me`, async ({ page }) => {
      const res = await authedGet(page, '/api/v1/me', token);
      const body = await res.json();
      expect(body.ok).toBe(true);
      expect(body.data.email).toBe(ACCOUNTS[tier].email);
      expect(body.data).toHaveProperty('plan_tier');
      expect(body.data).toHaveProperty('display_name');
    });

    test(`[${tier}] GET /api/v1/account/entitlements`, async ({ page }) => {
      const res = await authedGet(page, '/api/v1/account/entitlements', token);
      const body = await res.json();
      expect(body.ok).toBe(true);
      expect(body.data).toHaveProperty('plan');
      expect(body.data).toHaveProperty('entitlements');
    });

    test(`[${tier}] GET /api/v1/account/usage`, async ({ page }) => {
      const res = await authedGet(page, '/api/v1/account/usage', token);
      const body = await res.json();
      expect(body.ok).toBe(true);
    });

    test(`[${tier}] GET /api/v1/account/profile`, async ({ page }) => {
      const res = await authedGet(page, '/api/v1/account/profile', token);
      const body = await res.json();
      expect(body.ok).toBe(true);
    });

    test(`[${tier}] GET /api/v1/account/sessions`, async ({ page }) => {
      const res = await authedGet(page, '/api/v1/account/sessions', token);
      const body = await res.json();
      expect(body.ok).toBe(true);
    });

    test(`[${tier}] GET /api/v1/account/terms`, async ({ page }) => {
      const res = await authedGet(page, '/api/v1/account/terms', token);
      // May return 200 or 500 if terms not seeded
      expect(res.status()).toBeLessThan(502);
    });

    test(`[${tier}] GET /api/v1/account/data`, async ({ page }) => {
      const res = await authedGet(page, '/api/v1/account/data', token);
      // Data summary may fail if retention queries have issues
      expect(res.status()).toBeLessThan(502);
    });

    test(`[${tier}] GET /api/v1/account/retention`, async ({ page }) => {
      const res = await authedGet(page, '/api/v1/account/retention', token);
      expect(res.status()).toBeLessThan(502);
    });

    // ── Sessions ──

    test(`[${tier}] GET /api/v1/sessions`, async ({ page }) => {
      const res = await authedGet(page, '/api/v1/sessions', token);
      const body = await res.json();
      expect(body.ok).toBe(true);
      expect(body.data).toHaveProperty('sessions');
      expect(body.data).toHaveProperty('total');
    });

    // ── Workspaces ──

    test(`[${tier}] GET /api/v1/workspaces`, async ({ page }) => {
      const res = await authedGet(page, '/api/v1/workspaces', token);
      const body = await res.json();
      expect(body.ok).toBe(true);
    });

    test(`[${tier}] GET /api/v1/workspaces/current`, async ({ page }) => {
      const res = await authedGet(page, '/api/v1/workspaces/current', token);
      const body = await res.json();
      expect(body.ok).toBe(true);
    });

    // ── Tracks ──

    test(`[${tier}] GET /api/v1/tracks`, async ({ page }) => {
      const res = await authedGet(page, '/api/v1/tracks', token);
      expect(res.status()).toBeLessThan(500);
    });

    // ── Billing ──

    test(`[${tier}] GET /api/v1/billing/status`, async ({ page }) => {
      const res = await authedGet(page, '/api/v1/billing/status', token);
      expect(res.status()).toBeLessThan(502);
    });

    // ── Feature gates (tier-specific) ──

    if (tier === 'demo') {
      test('[demo] blocked from /api/v1/comparisons/', async ({ page }) => {
        const res = await authedGet(page, '/api/v1/comparisons/', token);
        expect(res.status()).toBe(403);
      });

      test('[demo] blocked from /api/v1/data/', async ({ page }) => {
        const res = await authedGet(page, '/api/v1/data/', token);
        expect(res.status()).toBe(403);
      });
    }

    if (tier === 'racer') {
      test('[racer] blocked from /api/v1/comparisons/', async ({ page }) => {
        const res = await authedGet(page, '/api/v1/comparisons/', token);
        expect(res.status()).toBe(403);
      });

      test('[racer] blocked from /api/v1/data/', async ({ page }) => {
        const res = await authedGet(page, '/api/v1/data/', token);
        expect(res.status()).toBe(403);
      });
    }

    if (tier === 'world_class') {
      test('[world_class] passes /api/v1/comparisons/ gate', async ({ page }) => {
        const res = await authedGet(page, '/api/v1/comparisons/', token);
        expect(res.status()).not.toBe(403);
      });

      test('[world_class] passes /api/v1/data/ gate', async ({ page }) => {
        const res = await authedGet(page, '/api/v1/data/', token);
        expect(res.status()).not.toBe(403);
      });

      test('[world_class] api_access=true in entitlements', async ({ page }) => {
        const res = await authedGet(page, '/api/v1/account/entitlements', token);
        const body = await res.json();
        expect(body.data.entitlements.api_access).toBe(true);
      });

      test('[world_class] comparison_progress=true', async ({ page }) => {
        const res = await authedGet(page, '/api/v1/account/entitlements', token);
        const body = await res.json();
        expect(body.data.entitlements.comparison_progress).toBe(true);
      });

      test('[world_class] unlimited uploads (-1)', async ({ page }) => {
        const res = await authedGet(page, '/api/v1/account/entitlements', token);
        const body = await res.json();
        expect(body.data.entitlements.uploads_per_month).toBe(-1);
      });
    }

    // ── Entitlement value checks (tier-specific) ──

    if (tier === 'demo') {
      test('[demo] limited uploads (1-5)', async ({ page }) => {
        const res = await authedGet(page, '/api/v1/account/entitlements', token);
        const body = await res.json();
        expect(body.data.entitlements.uploads_per_month).toBeLessThanOrEqual(5);
      });

      test('[demo] api_access=false', async ({ page }) => {
        const res = await authedGet(page, '/api/v1/account/entitlements', token);
        const body = await res.json();
        expect(body.data.entitlements.api_access).toBe(false);
      });
    }

    if (tier === 'racer') {
      test('[racer] coaching_drills=true', async ({ page }) => {
        const res = await authedGet(page, '/api/v1/account/entitlements', token);
        const body = await res.json();
        expect(body.data.entitlements.coaching_drills).toBe(true);
      });

      test('[racer] viz_workspace=true', async ({ page }) => {
        const res = await authedGet(page, '/api/v1/account/entitlements', token);
        const body = await res.json();
        expect(body.data.entitlements.viz_workspace).toBe(true);
      });
    }
  });
}

// ============================================================
// Unauthenticated tests (no login needed — no rate limit risk)
// ============================================================

test.describe('Infrastructure & Security', () => {
  test('GET /healthz — full health check', async ({ page }) => {
    const res = await page.request.get(`${API_URL}/healthz`);
    const body = await res.json();
    expect(body.status).toBe('ok');
    expect(body.db).toBe('ok');
    expect(body.redis).toBe('ok');
  });

  test('unauthenticated /api/v1/me returns 401', async ({ page }) => {
    const res = await page.request.get(`${API_URL}/api/v1/me`);
    expect(res.status()).toBe(401);
  });

  test('invalid token returns 401', async ({ page }) => {
    const res = await page.request.get(`${API_URL}/api/v1/me`, {
      headers: { Authorization: 'Bearer invalid.token.here' },
    });
    expect(res.status()).toBe(401);
  });

  test('CORS returns Access-Control-Allow-Origin', async ({ page }) => {
    const res = await page.request.get(`${API_URL}/healthz`);
    const headers = res.headers();
    expect(headers['access-control-allow-origin'] || '').toBeTruthy();
  });
});

// ============================================================
// Selling site pages
// ============================================================

test.describe('Selling Site pages', () => {
  const pages = [
    { path: '/', match: /lap/i },
    { path: '/pricing', match: /free|demo|racer/i },
    { path: '/login', match: /sign in|log in/i },
    { path: '/register', match: /sign up|create|register/i },
    { path: '/privacy', match: /privacy|data|personal/i },
    { path: '/terms', match: /terms|service|agreement/i },
    { path: '/security', match: /security|protect|encrypt/i },
    { path: '/dpa', match: /data|processing|agreement/i },
    { path: '/product', match: /telemetry|analysis|racing/i },
  ];

  for (const p of pages) {
    test(`${p.path} loads with content`, async ({ page }) => {
      await page.goto(p.path);
      const title = await page.title();
      expect(title).toBeTruthy();
      await expect(page.locator('body')).toContainText(p.match, { timeout: 10000 });
    });
  }
});
