import { test, expect } from '@playwright/test';

/**
 * Tracks list, detail, and evolution page E2E tests.
 *
 * Pages tested:
 *   /app/tracks           - TracksPage: DataTable with track name, country, city, sessions, record
 *   /app/tracks/:id       - TrackDetailPage: stat cards, chart panels, leaderboard table
 *   /app/tracks/:id/evolution - TrackEvolutionPage: canvas chart, date filters, session history table
 *
 * API endpoints mocked:
 *   GET /api/v1/tracks             - tracks list
 *   GET /api/v1/tracks/:id         - track detail
 *   GET /api/v1/tracks/:id/leaderboard - track leaderboard
 *   GET /api/v1/tracks/:id/evolution   - track evolution data
 */

const MOCK_TRACKS = {
  ok: true,
  data: {
    tracks: [
      { id: 1, name: 'Karting Arena', country: 'Spain', city: 'Barcelona', sessions_count: 24, best_time: 62.345 },
      { id: 2, name: 'Mugello Kart', country: 'Italy', city: 'Scarperia', sessions_count: 8, best_time: 55.112 },
      { id: 3, name: 'Le Mans Karting', country: 'France', city: 'Le Mans', sessions_count: 12, best_time: 48.890 },
    ],
  },
  meta: { request_id: 'test-tracks' },
};

const MOCK_TRACK_DETAIL = {
  ok: true,
  data: {
    id: 1,
    name: 'Karting Arena',
    country: 'Spain',
    city: 'Barcelona',
    sessions_count: 24,
    best_time: 62.345,
    best_driver: 'Max Speed',
    avg_score: 76.3,
  },
  meta: { request_id: 'test-track-detail' },
};

const MOCK_LEADERBOARD = {
  ok: true,
  data: {
    entries: [
      { rank: 1, driver_name: 'Max Speed', best_time: 62.345, date: '2026-02-20' },
      { rank: 2, driver_name: 'Ana Brakes', best_time: 63.112, date: '2026-02-18' },
    ],
  },
  meta: { request_id: 'test-leaderboard' },
};

const MOCK_EVOLUTION = {
  ok: true,
  data: {
    track_name: 'Karting Arena',
    record_time: 62.345,
    record_holder: 'Max Speed',
    sessions_count: 24,
    improvement_pct: 3.2,
    evolution: [
      { date: '2026-01-15', driver_name: 'Ana Brakes', best_time: 65.100, delta_to_record: 2.755 },
      { date: '2026-02-01', driver_name: 'Max Speed', best_time: 63.890, delta_to_record: 1.545 },
      { date: '2026-02-20', driver_name: 'Max Speed', best_time: 62.345, delta_to_record: 0 },
    ],
  },
  meta: { request_id: 'test-evolution' },
};

test.describe('Tracks list page', () => {
  test.beforeEach(async ({ page }) => {
    await page.context().addCookies([
      { name: 'access_token', value: 'test-token', domain: 'localhost', path: '/' },
    ]);

    await page.route('**/api/v1/tracks', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_TRACKS),
      });
    });
  });

  test('tracks list renders table with track data', async ({ page }) => {
    await page.goto('/app/tracks');

    // Page header
    await expect(page.getByText('Tracks')).toBeVisible();

    // Table headers
    await expect(page.getByText('Track')).toBeVisible();
    await expect(page.getByText('Country')).toBeVisible();
    await expect(page.getByText('City')).toBeVisible();
    await expect(page.getByText('Sessions')).toBeVisible();
    await expect(page.getByText('Record')).toBeVisible();

    // Row data
    await expect(page.getByText('Karting Arena')).toBeVisible();
    await expect(page.getByText('Spain')).toBeVisible();
    await expect(page.getByText('Mugello Kart')).toBeVisible();
    await expect(page.getByText('Italy')).toBeVisible();
    await expect(page.getByText('Le Mans Karting')).toBeVisible();
  });

  test('clicking a track row navigates to track detail', async ({ page }) => {
    // Mock detail endpoints for navigation
    await page.route('**/api/v1/tracks/1', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_TRACK_DETAIL),
      });
    });

    await page.route('**/api/v1/tracks/1/leaderboard', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_LEADERBOARD),
      });
    });

    await page.goto('/app/tracks');

    // Click the first track
    await page.getByText('Karting Arena').click();

    await expect(page).toHaveURL(/\/app\/tracks\/1/);
  });
});

test.describe('Track detail page', () => {
  test.beforeEach(async ({ page }) => {
    await page.context().addCookies([
      { name: 'access_token', value: 'test-token', domain: 'localhost', path: '/' },
    ]);

    await page.route('**/api/v1/tracks/1', async (route) => {
      // Only match exact /tracks/1 (not /tracks/1/leaderboard etc)
      const url = route.request().url();
      if (url.endsWith('/tracks/1') || url.endsWith('/tracks/1?')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(MOCK_TRACK_DETAIL),
        });
      }
    });

    await page.route('**/api/v1/tracks/1/leaderboard', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_LEADERBOARD),
      });
    });
  });

  test('track detail shows stat cards and leaderboard', async ({ page }) => {
    await page.goto('/app/tracks/1');

    // Header: track name and location
    await expect(page.getByText('Karting Arena')).toBeVisible();
    await expect(page.getByText(/Barcelona.*Spain/)).toBeVisible();

    // Stat cards
    await expect(page.getByText('Track Record')).toBeVisible();
    await expect(page.getByText('Record Holder')).toBeVisible();
    await expect(page.getByText('Max Speed')).toBeVisible();

    // Chart panels
    await expect(page.getByText('Track Evolution')).toBeVisible();
    await expect(page.getByText('Track Map')).toBeVisible();

    // Leaderboard
    await expect(page.getByText('Leaderboard')).toBeVisible();
    await expect(page.getByText('Ana Brakes')).toBeVisible();
  });
});

test.describe('Track evolution page', () => {
  test.beforeEach(async ({ page }) => {
    await page.context().addCookies([
      { name: 'access_token', value: 'test-token', domain: 'localhost', path: '/' },
    ]);

    await page.route('**/api/v1/tracks/1/evolution*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_EVOLUTION),
      });
    });
  });

  test('evolution page shows chart, stat cards, date filters, and session history', async ({
    page,
  }) => {
    await page.goto('/app/tracks/1/evolution');

    // Header: track name with "Track Evolution" subtitle
    await expect(page.getByText('Karting Arena')).toBeVisible();
    await expect(page.getByText('Track Evolution')).toBeVisible();

    // Stat cards
    await expect(page.getByText('Track Record')).toBeVisible();
    await expect(page.getByText('Record Holder')).toBeVisible();
    await expect(page.getByText('Sessions Analyzed')).toBeVisible();
    await expect(page.getByText('Improvement')).toBeVisible();

    // Date filter inputs
    await expect(page.getByText('From')).toBeVisible();
    await expect(page.getByText('To')).toBeVisible();

    // Canvas chart for evolution
    const canvas = page.locator('canvas');
    await expect(canvas).toBeVisible();

    // Session history table
    await expect(page.getByText('Session History')).toBeVisible();
    await expect(page.getByText('Delta to Record')).toBeVisible();
  });
});
