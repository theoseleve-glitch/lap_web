import { test, expect } from '@playwright/test';

/**
 * Full-flow smoke test — verifies core app flow works end-to-end.
 *
 * Mocks API responses to test:
 *   1. Session list renders
 *   2. Session detail page renders chart containers
 *   3. No uncaught JS errors
 */

const MOCK_SESSION = {
  session_id: 'smoke-001',
  csv_filename: 'smoke_test.csv',
  driver_name: 'Smoke Driver',
  track_name: 'Test Circuit',
  session_type: 'practice',
  track_state: 'dry',
  session_date: '2026-03-01',
  n_laps: 5,
  best_lap_time_s: 45.123,
  mean_lap_time_s: 46.500,
  total_score: 75.0,
  grade: 'B',
  notes: null,
};

const MOCK_LAPS = [
  { lap_number: 1, lap_time_s: 46.5, speed_mean_mps: 20.0, speed_max_mps: 28.0, is_valid: 1, is_best: 0, invalid_reason: null },
  { lap_number: 2, lap_time_s: 45.123, speed_mean_mps: 21.0, speed_max_mps: 29.0, is_valid: 1, is_best: 1, invalid_reason: null },
  { lap_number: 3, lap_time_s: 46.0, speed_mean_mps: 20.5, speed_max_mps: 28.5, is_valid: 1, is_best: 0, invalid_reason: null },
];

const MOCK_SCORES = {
  pace_score: 20, pace_max: 25,
  consistency_score: 18, consistency_max: 25,
  execution_score: 19, execution_max: 25,
  robustness_score: 18, robustness_max: 25,
  adaptation_score: null,
  strengths: ['Good pace'],
  weaknesses: ['Brake consistency'],
};

test.describe('Smoke flow', () => {
  test.beforeEach(async ({ page }) => {
    // Auth cookie
    await page.context().addCookies([
      { name: 'access_token', value: 'test-token', domain: 'localhost', path: '/' },
    ]);

    // Track console errors
    const consoleErrors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') consoleErrors.push(msg.text());
    });

    // Mock session list
    await page.route('**/api/v1/sessions', async (route) => {
      if (route.request().method() === 'GET') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            ok: true,
            data: [MOCK_SESSION],
            meta: { request_id: 'smoke-list' },
          }),
        });
      } else {
        await route.continue();
      }
    });

    // Mock session detail
    await page.route(`**/api/v1/sessions/smoke-001`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          data: MOCK_SESSION,
          meta: { request_id: 'smoke-detail' },
        }),
      });
    });

    // Mock laps
    await page.route('**/api/v1/sessions/smoke-001/laps', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          data: { laps: MOCK_LAPS },
          meta: { request_id: 'smoke-laps' },
        }),
      });
    });

    // Mock scores
    await page.route('**/api/v1/sessions/smoke-001/scores', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          data: MOCK_SCORES,
          meta: { request_id: 'smoke-scores' },
        }),
      });
    });

    // Mock chart data endpoints (return minimal valid data)
    const emptyArrayResponse = (fields: string[]) => {
      const data: Record<string, unknown[]> = {};
      for (const f of fields) data[f] = [];
      return data;
    };

    await page.route('**/api/v1/sessions/smoke-001/speed-trace*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          data: { distances: [0, 100, 200], speeds: [20, 25, 22], lap_number: 1 },
          meta: { request_id: 'smoke-speed' },
        }),
      });
    });

    await page.route('**/api/v1/sessions/smoke-001/gps-trace*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          data: {
            latitudes: [45.0, 45.001, 45.002],
            longitudes: [7.0, 7.001, 7.002],
            distances: [0, 100, 200],
            speeds: [20, 25, 22],
            lap_number: 1,
          },
          meta: { request_id: 'smoke-gps' },
        }),
      });
    });

    await page.route('**/api/v1/sessions/smoke-001/gg-data*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          data: { accel_lat: [0.1, -0.2], accel_long: [0.5, -0.3], lap_number: 1 },
          meta: { request_id: 'smoke-gg' },
        }),
      });
    });

    await page.route('**/api/v1/sessions/smoke-001/corners', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          data: emptyArrayResponse(['corners']),
          meta: { request_id: 'smoke-corners' },
        }),
      });
    });

    // Catch-all for other session sub-endpoints
    await page.route('**/api/v1/sessions/smoke-001/**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          data: {},
          meta: { request_id: 'smoke-fallback' },
        }),
      });
    });
  });

  test('session list renders with data', async ({ page }) => {
    await page.goto('/app/sessions');
    await page.waitForLoadState('networkidle');

    // Session should appear somewhere on the page
    await expect(page.getByText('Smoke Driver')).toBeVisible({ timeout: 10000 });
    await expect(page.getByText('Test Circuit')).toBeVisible();
  });

  test('session detail page renders chart containers', async ({ page }) => {
    await page.goto('/app/sessions/smoke-001');
    await page.waitForLoadState('networkidle');

    // Page should have session metadata
    await expect(page.getByText('Smoke Driver')).toBeVisible({ timeout: 10000 });

    // Chart containers should exist (even if vanilla JS doesn't fully init)
    const mapContainer = page.locator('#gps-map');
    const speedChart = page.locator('#speed-chart');

    // At least one chart container should be in the DOM
    const mapVisible = await mapContainer.isVisible().catch(() => false);
    const speedVisible = await speedChart.isVisible().catch(() => false);
    expect(mapVisible || speedVisible).toBe(true);
  });

  test('no uncaught page errors on session detail', async ({ page }) => {
    const pageErrors: string[] = [];
    page.on('pageerror', (err) => pageErrors.push(err.message));

    await page.goto('/app/sessions/smoke-001');
    await page.waitForLoadState('networkidle');

    // Allow a short settle time for async chart init
    await page.waitForTimeout(2000);

    // Filter out known benign errors (e.g., Leaflet tile loading when offline)
    const criticalErrors = pageErrors.filter(
      (e) => !e.includes('tile') && !e.includes('Leaflet') && !e.includes('ChunkLoadError'),
    );
    expect(criticalErrors).toEqual([]);
  });

  test('analytics page does not crash', async ({ page }) => {
    const pageErrors: string[] = [];
    page.on('pageerror', (err) => pageErrors.push(err.message));

    await page.goto('/app/analytics');
    await page.waitForLoadState('networkidle');

    // Check no error overlay
    const errorOverlay = page.locator('.error-overlay, [role="alert"]');
    expect(await errorOverlay.count()).toBe(0);
  });
});
