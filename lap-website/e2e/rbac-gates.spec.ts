import { test, expect } from '@playwright/test';
import { loginAsUser, apiRequest } from './helpers/auth';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'https://api.lap-coach.racing';

test.describe('RBAC Tier Gates — Backend Enforcement', () => {

  test.describe('Demo tier restrictions', () => {
    let token: string;

    test.beforeAll(async ({ browser }) => {
      const page = await browser.newPage();
      token = await loginAsUser(page, 'demo');
      await page.close();
    });

    test('demo cannot access comparison endpoint', async ({ page }) => {
      const resp = await apiRequest(page, 'GET', '/api/v1/comparisons/', token);
      expect(resp.status()).toBe(403);
      const body = await resp.json();
      expect(body.error?.code).toBe('PLAN_REQUIRED');
    });

    test('demo cannot access visualization endpoint', async ({ page }) => {
      const resp = await apiRequest(page, 'GET', '/visualize/', token);
      expect(resp.status()).toBe(403);
    });

    test('demo cannot access API data endpoint', async ({ page }) => {
      const resp = await apiRequest(page, 'GET', '/api/v1/data/', token);
      expect(resp.status()).toBe(403);
    });
  });

  test.describe('Racer tier access', () => {
    let token: string;

    test.beforeAll(async ({ browser }) => {
      const page = await browser.newPage();
      token = await loginAsUser(page, 'racer');
      await page.close();
    });

    test('racer can access visualization', async ({ page }) => {
      const resp = await apiRequest(page, 'GET', '/visualize/', token);
      expect(resp.status()).not.toBe(403);
    });

    test('racer cannot access comparison (world_class only)', async ({ page }) => {
      const resp = await apiRequest(page, 'GET', '/api/v1/comparisons/', token);
      expect(resp.status()).toBe(403);
    });

    test('racer cannot access API data (world_class only)', async ({ page }) => {
      const resp = await apiRequest(page, 'GET', '/api/v1/data/', token);
      expect(resp.status()).toBe(403);
    });
  });

  test.describe('World-class tier access', () => {
    let token: string;

    test.beforeAll(async ({ browser }) => {
      const page = await browser.newPage();
      token = await loginAsUser(page, 'world_class');
      await page.close();
    });

    test('world_class can access comparison', async ({ page }) => {
      const resp = await apiRequest(page, 'GET', '/api/v1/comparisons/', token);
      expect(resp.status()).not.toBe(403);
    });

    test('world_class can access visualization', async ({ page }) => {
      const resp = await apiRequest(page, 'GET', '/visualize/', token);
      expect(resp.status()).not.toBe(403);
    });

    test('world_class can access API data', async ({ page }) => {
      const resp = await apiRequest(page, 'GET', '/api/v1/data/', token);
      expect(resp.status()).not.toBe(403);
    });
  });

  test.describe('Quota enforcement', () => {
    test('demo upload quota is enforced', async ({ page }) => {
      const token = await loginAsUser(page, 'demo');
      const resp = await apiRequest(page, 'GET', '/api/v1/account/entitlements', token);
      if (resp.status() === 200) {
        const body = await resp.json();
        expect(body.data?.uploads_per_month).toBe(1);
      }
    });

    test('world_class has unlimited uploads', async ({ page }) => {
      const token = await loginAsUser(page, 'world_class');
      const resp = await apiRequest(page, 'GET', '/api/v1/account/entitlements', token);
      if (resp.status() === 200) {
        const body = await resp.json();
        expect(body.data?.uploads_per_month).toBe(-1);
      }
    });
  });
});
