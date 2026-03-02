import { test, expect } from '@playwright/test';

/**
 * Critical path E2E tests for main app routes.
 *
 * These tests verify that key pages load successfully and render expected UI elements.
 * Mock API responses are used to simulate backend data.
 */

test.describe('Critical Path', () => {
  /**
   * Mock helper to set up common session list response
   */
  async function mockSessionsAPI(page: any) {
    await page.route('**/api/v1/sessions*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          data: {
            sessions: [
              {
                id: '1',
                driver_id: 1,
                track_id: 1,
                date: '2024-03-01',
                duration_seconds: 600,
                notes: 'Test session 1',
                score: 85,
              },
              {
                id: '2',
                driver_id: 1,
                track_id: 1,
                date: '2024-03-02',
                duration_seconds: 650,
                notes: 'Test session 2',
                score: 88,
              },
            ],
            total: 2,
            page: 1,
            page_size: 50,
          },
          meta: { request_id: 'test-req-1' },
        }),
      });
    });
  }

  test('session list loads and shows sessions', async ({ page }) => {
    await mockSessionsAPI(page);

    await page.goto('/app/sessions');

    // Wait for page to load with increased timeout
    await expect(page.locator('text=Sessions')).toBeVisible({ timeout: 10_000 });

    // Check for either table or empty state
    const hasTable = await page.locator('table').count();
    const hasEmpty = await page.locator('text=No sessions').count();
    expect(hasTable + hasEmpty).toBeGreaterThan(0);
  });

  test('session detail page loads with tabs', async ({ page }) => {
    // Mock sessions list
    await mockSessionsAPI(page);

    // Mock session detail endpoint
    await page.route('**/api/v1/sessions/1*', async (route) => {
      if (route.request().method() === 'GET') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            ok: true,
            data: {
              id: '1',
              driver_id: 1,
              driver_name: 'Test Driver',
              track_id: 1,
              track_name: 'Test Track',
              date: '2024-03-01',
              duration_seconds: 600,
              notes: 'Test session detail',
              score: 85,
              lap_count: 5,
            },
            meta: { request_id: 'test-req-2' },
          }),
        });
      }
    });

    // Mock laps endpoint
    await page.route('**/api/v1/sessions/1/laps*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          data: { laps: [], total: 0 },
          meta: { request_id: 'test-req-3' },
        }),
      });
    });

    await page.goto('/app/sessions');
    await page.waitForSelector('a[href*="/app/sessions/"]', { timeout: 10_000 });

    // Click first session link
    await page.click('a[href*="/app/sessions/"]');

    // Wait for detail page to load
    await expect(page.locator('text=Overview')).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('text=Laps')).toBeVisible();
  });

  test('drivers page loads', async ({ page }) => {
    await page.route('**/api/v1/drivers*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          data: { drivers: [], total: 0 },
          meta: { request_id: 'test-req-4' },
        }),
      });
    });

    await page.goto('/app/drivers');
    await expect(page.locator('text=Drivers')).toBeVisible({ timeout: 10_000 });
  });

  test('tracks page loads', async ({ page }) => {
    await page.route('**/api/v1/tracks*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          data: { tracks: [], total: 0 },
          meta: { request_id: 'test-req-5' },
        }),
      });
    });

    await page.goto('/app/tracks');
    await expect(page.locator('text=Tracks')).toBeVisible({ timeout: 10_000 });
  });

  test('compare hub loads', async ({ page }) => {
    await mockSessionsAPI(page);

    await page.route('**/api/v1/drivers*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          data: { drivers: [], total: 0 },
          meta: { request_id: 'test-req-6' },
        }),
      });
    });

    await page.goto('/app/compare');
    await expect(page.locator('text=Compare')).toBeVisible({ timeout: 10_000 });
  });

  test('race strategy list loads', async ({ page }) => {
    await page.route('**/api/v1/race-strategy*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          data: { strategies: [], total: 0 },
          meta: { request_id: 'test-req-7' },
        }),
      });
    });

    await page.goto('/app/race-strategy');
    await expect(page.locator('text=Race Strategy')).toBeVisible({ timeout: 10_000 });
  });

  test('dashboard loads with stats', async ({ page }) => {
    await page.route('**/api/v1/dashboard/stats', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          data: {
            total_sessions: 5,
            pb_time: 62.345,
            avg_score: 82.5,
            total_drivers: 2,
            recent_scores: [],
            recent_times: [],
            recent_sessions: [],
          },
          meta: { request_id: 'test-req-8' },
        }),
      });
    });

    await page.goto('/app/dashboard');
    await expect(page.locator('text=Dashboard')).toBeVisible({ timeout: 10_000 });
  });
});
