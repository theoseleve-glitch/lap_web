import { test, expect } from '@playwright/test';

/**
 * Compare sessions E2E tests.
 *
 * Page tested:
 *   /app/compare/sessions - CompareSessionsPage: two session selectors (dropdowns with search),
 *                           comparison results with stat cards, score breakdown, and overlay chart.
 *
 * API endpoints mocked:
 *   GET /api/v1/sessions              - session list for dropdowns
 *   GET /api/v1/compare/sessions?a=&b= - comparison results
 */

const MOCK_SESSION_LIST = {
  ok: true,
  data: {
    sessions: [
      { id: 'sess-001', label: 'Karting Arena - Max Speed - 2026-02-20' },
      { id: 'sess-002', label: 'Circuit de Barcelona - Ana Brakes - 2026-02-18' },
      { id: 'sess-003', label: 'Mugello Kart - Max Speed - 2026-02-10' },
    ],
  },
  meta: { request_id: 'test-sessions-list' },
};

const MOCK_COMPARISON = {
  ok: true,
  data: {
    session_a: {
      id: 'sess-001',
      track_name: 'Karting Arena',
      driver_name: 'Max Speed',
      date: '2026-02-20',
      laps: 15,
      best_time: 62.345,
      score: 82.4,
      grade: 'A',
      pace_score: 22.1,
      consistency_score: 21.3,
      execution_score: 19.5,
      robustness_score: 19.5,
    },
    session_b: {
      id: 'sess-002',
      track_name: 'Circuit de Barcelona',
      driver_name: 'Ana Brakes',
      date: '2026-02-18',
      laps: 22,
      best_time: 98.112,
      score: 71.8,
      grade: 'B',
      pace_score: 18.5,
      consistency_score: 19.2,
      execution_score: 17.1,
      robustness_score: 17.0,
    },
  },
  meta: { request_id: 'test-compare' },
};

test.describe('Compare sessions page', () => {
  test.beforeEach(async ({ page }) => {
    await page.context().addCookies([
      { name: 'access_token', value: 'test-token', domain: 'localhost', path: '/' },
    ]);

    await page.route('**/api/v1/sessions', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_SESSION_LIST),
      });
    });

    await page.route('**/api/v1/compare/sessions*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_COMPARISON),
      });
    });
  });

  test('compare page renders with session selectors', async ({ page }) => {
    await page.goto('/app/compare/sessions');

    // Page header
    await expect(page.getByText('Compare Sessions')).toBeVisible();
    await expect(
      page.getByText('Select two sessions to compare side-by-side'),
    ).toBeVisible();

    // Session A and Session B selector labels
    await expect(page.getByText('Session A')).toBeVisible();
    await expect(page.getByText('Session B')).toBeVisible();

    // Search inputs for filtering sessions
    const searchInputs = page.getByPlaceholder('Search sessions...');
    await expect(searchInputs.first()).toBeVisible();

    // Empty state message when no sessions are selected
    await expect(
      page.getByText('Select two different sessions above to begin comparison.'),
    ).toBeVisible();
  });

  test('selecting two sessions shows comparison results', async ({ page }) => {
    await page.goto('/app/compare/sessions');

    // Select Session A from the first dropdown
    const selectA = page.locator('select').first();
    await selectA.selectOption('sess-001');

    // Select Session B from the second dropdown
    const selectB = page.locator('select').last();
    await selectB.selectOption('sess-002');

    // Wait for comparison data to load
    await expect(page.getByText('Key Metrics')).toBeVisible();

    // Session headers should show track names
    await expect(page.getByText('Karting Arena')).toBeVisible();
    await expect(page.getByText('Circuit de Barcelona')).toBeVisible();

    // Score breakdown section
    await expect(page.getByText('Score Breakdown')).toBeVisible();

    // Overlay chart placeholder
    await expect(page.getByText('Lap Time Overlay')).toBeVisible();
  });
});
