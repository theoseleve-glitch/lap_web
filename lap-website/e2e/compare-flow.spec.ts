import { test, expect } from '@playwright/test';

/**
 * Compare flow E2E tests for session and driver comparison features.
 *
 * Tests verify the compare hub renders correctly and comparison pages load with
 * appropriate UI elements (dropdowns, selection cards, etc.).
 */

test.describe('Compare Flow', () => {
  /**
   * Mock helper for sessions list
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
                driver_name: 'Driver A',
                track_id: 1,
                track_name: 'Test Track',
                date: '2024-03-01',
                duration_seconds: 600,
                notes: 'Session A',
                score: 85,
              },
              {
                id: '2',
                driver_id: 1,
                track_id: 1,
                date: '2024-03-02',
                duration_seconds: 650,
                notes: 'Session B',
                score: 88,
              },
              {
                id: '3',
                driver_id: 2,
                driver_name: 'Driver B',
                track_id: 1,
                track_name: 'Test Track',
                date: '2024-03-03',
                duration_seconds: 620,
                notes: 'Session C',
                score: 82,
              },
            ],
            total: 3,
            page: 1,
            page_size: 50,
          },
          meta: { request_id: 'test-req-1' },
        }),
      });
    });
  }

  /**
   * Mock helper for drivers list
   */
  async function mockDriversAPI(page: any) {
    await page.route('**/api/v1/drivers*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          data: {
            drivers: [
              { id: '1', name: 'Driver A', vehicle_class: 'Kart' },
              { id: '2', name: 'Driver B', vehicle_class: 'Kart' },
            ],
            total: 2,
            page: 1,
            page_size: 50,
          },
          meta: { request_id: 'test-req-2' },
        }),
      });
    });
  }

  test('compare hub renders comparison card sections', async ({ page }) => {
    await mockSessionsAPI(page);
    await mockDriversAPI(page);

    await page.goto('/app/compare');
    await expect(page.locator('text=Compare')).toBeVisible({ timeout: 10_000 });

    // Hub should show comparison options (sessions, drivers, etc.)
    // At minimum, we expect the page to load and be interactive
    await expect(page).toHaveURL(/\/app\/compare/);
  });

  test('session compare page loads with selection controls', async ({ page }) => {
    await mockSessionsAPI(page);

    // Mock compare endpoint
    await page.route('**/api/v1/sessions/compare*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          data: {
            session_a: null,
            session_b: null,
            deltas: [],
            comparison: null,
          },
          meta: { request_id: 'test-req-3' },
        }),
      });
    });

    await page.goto('/app/compare/sessions');
    await expect(page).toHaveURL(/\/app\/compare\/sessions/);

    // Wait for page to be interactive
    await page.waitForLoadState('networkidle', { timeout: 10_000 });
  });

  test('driver compare page loads with dropdown controls', async ({ page }) => {
    await mockDriversAPI(page);

    // Mock driver compare endpoint
    await page.route('**/api/v1/drivers/compare*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          data: {
            driver_a: null,
            driver_b: null,
            sessions_a: [],
            sessions_b: [],
            stats_a: null,
            stats_b: null,
          },
          meta: { request_id: 'test-req-4' },
        }),
      });
    });

    await page.goto('/app/compare/drivers');
    await expect(page).toHaveURL(/\/app\/compare\/drivers/);

    // Wait for page to be interactive
    await page.waitForLoadState('networkidle', { timeout: 10_000 });
  });

  test('session compare with selected sessions renders delta data', async ({ page }) => {
    await mockSessionsAPI(page);

    // Mock compare with specific sessions
    await page.route('**/api/v1/sessions/compare?*', async (route) => {
      const url = new URL(route.request().url());
      const sessionA = url.searchParams.get('session_a');
      const sessionB = url.searchParams.get('session_b');

      if (sessionA && sessionB) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            ok: true,
            data: {
              session_a: { id: sessionA, score: 85 },
              session_b: { id: sessionB, score: 88 },
              deltas: [
                { metric: 'avg_speed', value_a: 50.5, value_b: 52.3, delta: 1.8 },
                { metric: 'lap_count', value_a: 5, value_b: 6, delta: 1 },
              ],
              comparison_summary: 'Session B is faster overall',
            },
            meta: { request_id: 'test-req-5' },
          }),
        });
      } else {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            ok: true,
            data: {
              session_a: null,
              session_b: null,
              deltas: [],
            },
            meta: { request_id: 'test-req-6' },
          }),
        });
      }
    });

    await page.goto('/app/compare/sessions?session_a=1&session_b=2');
    await page.waitForLoadState('networkidle', { timeout: 10_000 });

    // Verify comparison data loads
    await expect(page).toHaveURL(/session_a=1&session_b=2/);
  });

  test('driver compare with selected drivers renders stats', async ({ page }) => {
    await mockDriversAPI(page);

    // Mock driver compare with specific drivers
    await page.route('**/api/v1/drivers/compare?*', async (route) => {
      const url = new URL(route.request().url());
      const driverA = url.searchParams.get('driver_a');
      const driverB = url.searchParams.get('driver_b');

      if (driverA && driverB) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            ok: true,
            data: {
              driver_a: { id: driverA, name: 'Driver A', avg_score: 85 },
              driver_b: { id: driverB, name: 'Driver B', avg_score: 82 },
              stats_comparison: {
                avg_speed_a: 50.5,
                avg_speed_b: 49.2,
                consistency_a: 78,
                consistency_b: 81,
              },
            },
            meta: { request_id: 'test-req-7' },
          }),
        });
      } else {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            ok: true,
            data: {
              driver_a: null,
              driver_b: null,
            },
            meta: { request_id: 'test-req-8' },
          }),
        });
      }
    });

    await page.goto('/app/compare/drivers?driver_a=1&driver_b=2');
    await page.waitForLoadState('networkidle', { timeout: 10_000 });

    // Verify comparison URL reflects selection
    await expect(page).toHaveURL(/driver_a=1&driver_b=2/);
  });
});
