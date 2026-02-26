import { test, expect } from '@playwright/test';

/**
 * Sessions list + detail + corner replay E2E tests.
 *
 * Pages tested:
 *   /app/sessions         - SessionsPage: DataTable with search, stat cards
 *   /app/sessions/:id     - SessionDetailPage: stat cards, 4 chart tabs (Overview, Pace, Style, Physics), lap table
 *   /app/sessions/:id/corners/:cornerId - CornerReplayPage: CornerReplay component with map + cockpit + controls
 *
 * API endpoints mocked:
 *   GET /api/v1/sessions/browse      - sessions list
 *   GET /api/v1/sessions/:id/details - session detail
 *   GET /api/v1/sessions/:id/laps    - lap times
 *   GET /api/v1/sessions/:id/corners/:cornerId/replay - corner replay data
 */

const MOCK_SESSIONS_BROWSE = {
  ok: true,
  data: {
    sessions: [
      {
        id: 'sess-001',
        date: '2026-02-20',
        track_name: 'Karting Arena',
        driver_name: 'Max Speed',
        laps: 15,
        best_time: 62.345,
        score: 82.4,
        grade: 'A',
      },
      {
        id: 'sess-002',
        date: '2026-02-18',
        track_name: 'Circuit de Barcelona',
        driver_name: 'Ana Brakes',
        laps: 22,
        best_time: 98.112,
        score: 71.8,
        grade: 'B',
      },
    ],
    total: 2,
    avg_score: 77.1,
    best_lap: 62.345,
    active_drivers: 2,
  },
  meta: { request_id: 'test-browse' },
};

const MOCK_SESSION_DETAIL = {
  ok: true,
  data: {
    id: 'sess-001',
    date: '2026-02-20',
    track_name: 'Karting Arena',
    driver_name: 'Max Speed',
    laps: 15,
    best_time: 62.345,
    score: 82.4,
    grade: 'A',
    consistency_score: 21.3,
    pace_score: 22.1,
    execution_score: 19.5,
    robustness_score: 19.5,
  },
  meta: { request_id: 'test-detail' },
};

const MOCK_SESSION_LAPS = {
  ok: true,
  data: {
    laps: [
      { lap_number: 1, time: 64.123, speed_avg: 78.2, valid: true },
      { lap_number: 2, time: 63.456, speed_avg: 79.1, valid: true },
      { lap_number: 3, time: 62.345, speed_avg: 80.3, valid: true },
    ],
  },
  meta: { request_id: 'test-laps' },
};

test.describe('Sessions list page', () => {
  test.beforeEach(async ({ page }) => {
    await page.context().addCookies([
      { name: 'access_token', value: 'test-token', domain: 'localhost', path: '/' },
    ]);

    await page.route('**/api/v1/sessions/browse*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_SESSIONS_BROWSE),
      });
    });
  });

  test('sessions list renders table with session data', async ({ page }) => {
    await page.goto('/app/sessions');

    // Page header
    await expect(page.getByText('Sessions')).toBeVisible();

    // Stat cards
    await expect(page.getByText('Total Sessions')).toBeVisible();
    await expect(page.getByText('Avg Score')).toBeVisible();
    await expect(page.getByText('Best Lap')).toBeVisible();
    await expect(page.getByText('Active Drivers')).toBeVisible();

    // Search input
    await expect(
      page.getByPlaceholder('Search sessions by track, driver...'),
    ).toBeVisible();

    // Table headers
    await expect(page.getByText('Date')).toBeVisible();
    await expect(page.getByText('Track')).toBeVisible();
    await expect(page.getByText('Driver')).toBeVisible();

    // Row data
    await expect(page.getByText('Karting Arena')).toBeVisible();
    await expect(page.getByText('Max Speed')).toBeVisible();
    await expect(page.getByText('Ana Brakes')).toBeVisible();
  });

  test('clicking a session row navigates to session detail', async ({ page }) => {
    // Also mock the detail endpoints so the detail page can load
    await page.route('**/api/v1/sessions/sess-001/details', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_SESSION_DETAIL),
      });
    });

    await page.route('**/api/v1/sessions/sess-001/laps', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_SESSION_LAPS),
      });
    });

    await page.goto('/app/sessions');

    // Click the first row (Karting Arena)
    await page.getByText('Karting Arena').click();

    // Should navigate to session detail
    await expect(page).toHaveURL(/\/app\/sessions\/sess-001/);
  });
});

test.describe('Session detail page', () => {
  test.beforeEach(async ({ page }) => {
    await page.context().addCookies([
      { name: 'access_token', value: 'test-token', domain: 'localhost', path: '/' },
    ]);

    await page.route('**/api/v1/sessions/sess-001/details', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_SESSION_DETAIL),
      });
    });

    await page.route('**/api/v1/sessions/sess-001/laps', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_SESSION_LAPS),
      });
    });

    // Mock chart data endpoints -- return empty data so charts render containers
    await page.route('**/api/v1/sessions/sess-001/**', async (route) => {
      // Let the detail and laps requests through (already mocked above),
      // fulfill all other sub-routes with empty data
      const url = route.request().url();
      if (url.includes('/details') || url.includes('/laps')) {
        // These are handled by specific routes above; skip
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          data: { points: [], labels: [] },
          meta: { request_id: 'test-chart' },
        }),
      });
    });
  });

  test('session detail shows score cards and chart tabs', async ({ page }) => {
    await page.goto('/app/sessions/sess-001');

    // Header: track name
    await expect(page.getByText('Karting Arena')).toBeVisible();

    // Driver and date in subtitle
    await expect(page.getByText(/Max Speed/)).toBeVisible();

    // Score stat cards
    await expect(page.getByText('Best Time')).toBeVisible();
    await expect(page.getByText('Total Laps')).toBeVisible();
    await expect(page.getByText('Score')).toBeVisible();
    await expect(page.getByText('Grade')).toBeVisible();

    // Score breakdown
    await expect(page.getByText('Pace')).toBeVisible();
    await expect(page.getByText('Consistency')).toBeVisible();
    await expect(page.getByText('Execution')).toBeVisible();
    await expect(page.getByText('Robustness')).toBeVisible();

    // Chart tabs: Overview is active by default
    const overviewTab = page.getByRole('button', { name: 'Overview' });
    await expect(overviewTab).toBeVisible();
    await expect(page.getByRole('button', { name: 'Pace' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Style' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Physics' })).toBeVisible();
  });

  test('switching chart tabs updates the chart container', async ({ page }) => {
    await page.goto('/app/sessions/sess-001');

    // Click the "Pace" tab
    await page.getByRole('button', { name: 'Pace' }).click();

    // The chart grid (grid container under the tabs) should be visible
    // After switching to "Pace" tab, the chart area re-renders
    const chartGrid = page.locator('.grid.grid-cols-1');
    await expect(chartGrid.first()).toBeVisible();

    // Click the "Style" tab
    await page.getByRole('button', { name: 'Style' }).click();
    await expect(chartGrid.first()).toBeVisible();

    // Click the "Physics" tab
    await page.getByRole('button', { name: 'Physics' }).click();
    await expect(chartGrid.first()).toBeVisible();
  });

  test('lap times table renders', async ({ page }) => {
    await page.goto('/app/sessions/sess-001');

    // The lap times table header
    await expect(page.getByText('Lap Times')).toBeVisible();

    // Lap data is present
    await expect(page.getByText('78.2 km/h')).toBeVisible();
  });
});

test.describe('Corner replay page', () => {
  test.beforeEach(async ({ page }) => {
    await page.context().addCookies([
      { name: 'access_token', value: 'test-token', domain: 'localhost', path: '/' },
    ]);

    await page.route(
      '**/api/v1/sessions/sess-001/corners/3/replay',
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            ok: true,
            data: {
              corner_id: 3,
              corner_name: 'Turn 3',
              frames: [
                { time: 0, speed: 85, throttle: 0.8, brake: 0, steeringAngle: -5, gLat: 0.3, gLon: 1.2, lat: 41.57, lon: 2.26 },
                { time: 0.1, speed: 82, throttle: 0.2, brake: 0.6, steeringAngle: -15, gLat: 0.8, gLon: 0.9, lat: 41.571, lon: 2.261 },
                { time: 0.2, speed: 78, throttle: 0.5, brake: 0.1, steeringAngle: -10, gLat: 0.5, gLon: 1.0, lat: 41.572, lon: 2.262 },
              ],
              gps_path: [
                { lat: 41.57, lon: 2.26 },
                { lat: 41.571, lon: 2.261 },
                { lat: 41.572, lon: 2.262 },
              ],
              total_time: 0.2,
            },
            meta: { request_id: 'test-replay' },
          }),
        });
      },
    );
  });

  test('corner replay page loads and renders component', async ({ page }) => {
    await page.goto('/app/sessions/sess-001/corners/3');

    // The CornerReplay component renders within a full-height container.
    // It should not show the "Invalid corner ID" error.
    await expect(page.getByText('Invalid corner ID')).not.toBeVisible();

    // The page should have a visible container element
    const container = page.locator('[class*="h-[calc"]');
    await expect(container).toBeVisible();
  });
});
