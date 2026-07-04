import { test, expect } from '@playwright/test';

/**
 * Race strategy E2E tests — endurance-finish (W2) coverage.
 *
 * Pages tested:
 *   /app/race-strategy              - list page
 *   /app/race-strategy/new          - create form (RaceConfigForm)
 *   /app/race-strategy/[id]         - draft/ready detail (optimize, go-live,
 *                                     strategy comparison)
 *   /app/race-strategy/[id]/live    - live dashboard (2s state polling)
 *   /app/race-strategy/[id]/summary - post-race summary (planned-vs-actual
 *                                     for retrospective/session-linked races)
 *
 * All API calls are mocked — no real backend required.
 */

const AUTH_COOKIE = { name: 'access_token', value: 'test-token', domain: 'localhost', path: '/' };

/** A minimal, correctly-shaped GET /api/v1/me response with racer-tier
 * entitlements (matches MeResponse in useEntitlements.ts). */
const ME_RESPONSE = {
  ok: true,
  data: {
    id: 1,
    email: 'racer@test.local',
    display_name: 'Test Racer',
    entitlements: {
      plan_tier: 'racer',
      subscription_status: 'active',
      analyses_per_month: 10,
      analyses_used: 1,
      analyses_remaining: 9,
      upload_volume_mb_per_month: 2500,
      upload_volume_mb_used: 0,
      upload_volume_mb_remaining: 2500,
      api_access: false,
      comparison_enabled: true,
      coaching_plans_enabled: true,
      visualization_enabled: true,
      badge_share_card: true,
      gamification: true,
      race_strategy_limit: '24h_complex',
      race_strategy_max_duration_s: 86400,
      race_strategy_params: 'complex',
      optimizer_modes: ['equal'],
      live_monitoring: true,
      export_formats: ['csv', 'pdf'],
      telemetry_retention_days: 90,
      max_upload_size_mb: 2500,
      max_session_data_mb: 2500,
      max_concurrent_jobs: 1,
      rate_multiplier: 1.0,
    },
  },
  meta: { request_id: 'test-me' },
};

async function mockMe(page: import('@playwright/test').Page) {
  await page.route('**/api/v1/me', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(ME_RESPONSE) });
  });
}

test.describe('Race strategy list page', () => {
  test.beforeEach(async ({ page }) => {
    await page.context().addCookies([{ ...AUTH_COOKIE }]);
    await mockMe(page);

    await page.route('**/api/v1/race-strategy/', async (route) => {
      if (route.request().method() !== 'GET') return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          data: {
            races: [
              { race_id: 1, race_name: 'Sunday Sprint', track_name: 'Karting Arena', team_name: null, race_duration_s: 5400, desired_stints: 2, status: 'ready', created_at: '2026-02-19' },
              { race_id: 2, race_name: 'Endurance 3H', track_name: 'Mugello Kart', team_name: 'Apex Racing', race_duration_s: 10800, desired_stints: 3, status: 'draft', created_at: '2026-02-15' },
            ],
          },
          meta: { request_id: 'test-races' },
        }),
      });
    });
  });

  test('renders the sidebar nav link and the race list', async ({ page }) => {
    await page.goto('/app/dashboard');
    await expect(page.getByRole('link', { name: /race strategy/i })).toBeVisible();

    await page.goto('/app/race-strategy');
    await expect(page.getByText('Race Strategy')).toBeVisible();
    await expect(page.getByText('Sunday Sprint')).toBeVisible();
    await expect(page.getByText('Endurance 3H')).toBeVisible();
    await expect(page.getByRole('link', { name: '+ New Race' })).toBeVisible();
  });

  test('clicking + New Race navigates to the creation form', async ({ page }) => {
    await page.goto('/app/race-strategy');
    await page.getByRole('link', { name: '+ New Race' }).click();
    await expect(page).toHaveURL(/\/app\/race-strategy\/new/);
  });
});

test.describe('Create -> optimize -> go-live -> summary journey', () => {
  test.beforeEach(async ({ page }) => {
    await page.context().addCookies([{ ...AUTH_COOKIE }]);
    await mockMe(page);
  });

  test('new race form submits and redirects to the detail page', async ({ page }) => {
    await page.route('**/api/v1/race-strategy/', async (route) => {
      if (route.request().method() !== 'POST') return route.fallback();
      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({ ok: true, data: { race_id: 42 }, meta: { request_id: 'test-create' } }),
      });
    });

    await page.goto('/app/race-strategy/new');
    await expect(page.getByText('New Race')).toBeVisible();

    await page.getByLabel('Race Name *').fill('Test 3h Endurance');
    await page.getByLabel(/Driver 1 name/i).fill('Alice');
    await page.getByLabel(/Driver 2 name/i).fill('Bob');

    await page.getByRole('button', { name: 'Create Race' }).click();
    await expect(page).toHaveURL(/\/app\/race-strategy\/42$/);
  });

  test('detail page shows Optimize, Go Live, and the strategy comparison action', async ({ page }) => {
    // status 'ready' (i.e. post-optimize, feasible) is required for the
    // Go Live button to render — see [id]/page.tsx: `race.status === 'ready'
    // && !showGoLiveConfirm`. 'draft' would hide it.
    const raceDetail = {
      race: {
        race_id: 42, race_name: 'Test 3h Endurance', track_name: null, team_name: null,
        race_duration_s: 10800, desired_stints: 2, fuel_autonomy_s: null, min_pit_stop_s: 60,
        empty_kart_kg: null, full_tank_kg: null, min_total_kart_kg: null, reference_weight_kg: null,
        status: 'ready', race_start_ts: null, created_at: '2026-07-02',
      },
      drivers: [
        { id: 1, driver_name: 'Alice', driver_order: 1, weight_kg: null, com_channel: null, color_hex: '#3B82F6', min_stint_s: null, max_stint_s: null },
        { id: 2, driver_name: 'Bob', driver_order: 2, weight_kg: null, com_channel: null, color_hex: '#EF4444', min_stint_s: null, max_stint_s: null },
      ],
      stints: [
        { stint_id: 1, stint_order: 1, driver_id: 1, driver_name: 'Alice', planned_start_s: 0, planned_end_s: 5400, planned_duration_s: 5400, actual_start_s: null, actual_end_s: null, actual_duration_s: null, fuel_at_start: null, fuel_at_end: null, ballast_kg: null, estimated_laps: null, pit_at_lap: null, status: 'planned' },
        { stint_id: 2, stint_order: 2, driver_id: 2, driver_name: 'Bob', planned_start_s: 5460, planned_end_s: 10800, planned_duration_s: 5340, actual_start_s: null, actual_end_s: null, actual_duration_s: null, fuel_at_start: null, fuel_at_end: null, ballast_kg: null, estimated_laps: null, pit_at_lap: null, status: 'planned' },
      ],
      pit_stops: [],
      windows: [],
    };

    await page.route('**/api/v1/race-strategy/42', async (route) => {
      if (route.request().method() !== 'GET') return route.fallback();
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, data: raceDetail, meta: {} }) });
    });

    await page.goto('/app/race-strategy/42');

    await expect(page.getByRole('button', { name: 'Optimize' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Go Live' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Compare Strategies' })).toBeVisible();
  });

  test('live page polls race state every 2s and reflects an update', async ({ page }) => {
    let pollCount = 0;
    const baseLiveState = {
      race: {
        race_id: 42, race_name: 'Test 3h Endurance', track_name: null, team_name: null,
        race_duration_s: 10800, desired_stints: 2, fuel_autonomy_s: null, min_pit_stop_s: 60,
        empty_kart_kg: null, full_tank_kg: null, min_total_kart_kg: null, reference_weight_kg: null,
        status: 'live', race_start_ts: new Date(Date.now() - 60_000).toISOString(),
        paused_at_ts: null, total_paused_s: 0, created_at: '2026-07-02',
      },
      drivers: [
        { id: 1, driver_name: 'Alice', driver_order: 1, weight_kg: null, com_channel: null, color_hex: '#3B82F6', min_stint_s: null, max_stint_s: null, min_cumulative_s: null, max_cumulative_s: null, avg_lap_time_s: 62 },
      ],
      stints: [
        { stint_id: 1, stint_order: 1, driver_id: 1, driver_name: 'Alice', planned_start_s: 0, planned_end_s: 5400, planned_duration_s: 5400, actual_start_s: 0, actual_end_s: null, actual_duration_s: null, fuel_at_start: 10, fuel_at_end: 5, ballast_kg: 0, actual_laps: null, status: 'active' },
      ],
      pit_stops: [], windows: [], messages: [],
      active_stint: { stint_id: 1, stint_order: 1, driver_id: 1, driver_name: 'Alice', planned_start_s: 0, planned_end_s: 5400, planned_duration_s: 5400, actual_start_s: 0, actual_end_s: null, actual_duration_s: null, fuel_at_start: 10, fuel_at_end: 5, ballast_kg: 0, actual_laps: null, status: 'active' },
      next_stint: null, in_pit: false, pit_elapsed_s: 0, driver_cumulative: {},
    };

    await page.route('**/api/v1/race-strategy/42/state', async (route) => {
      pollCount += 1;
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, data: baseLiveState, meta: {} }) });
    });

    await page.goto('/app/race-strategy/42/live');
    await expect(page.getByText('Test 3h Endurance')).toBeVisible();

    await expect.poll(() => pollCount, { timeout: 6000 }).toBeGreaterThan(1);
  });

  test('summary page shows Planned vs Actual for a retrospective (session-linked) race', async ({ page }) => {
    const summary = {
      race: {
        race_id: 42, race_name: 'Endurance session abc12345', track_name: null, team_name: null,
        race_duration_s: 3720, desired_stints: 2, fuel_autonomy_s: null, min_pit_stop_s: 60,
        empty_kart_kg: null, full_tank_kg: null, min_total_kart_kg: null, reference_weight_kg: null,
        status: 'finished', is_retrospective: true, race_start_ts: null, created_at: '2026-07-02',
      },
      drivers: [{ id: 1, driver_name: 'Alice', driver_order: 1, weight_kg: null, com_channel: null, color_hex: '#3B82F6', min_stint_s: null, max_stint_s: null }],
      stints: [{ stint_id: 1, stint_order: 1, driver_id: 1, driver_name: 'Alice', planned_start_s: 0, planned_end_s: 3720, planned_duration_s: 3720, actual_start_s: 0, actual_end_s: 3720, actual_duration_s: 3720, fuel_at_start: null, fuel_at_end: null, ballast_kg: null, status: 'completed' }],
      pit_stops: [], windows: [],
      driver_stats: { 1: { name: 'Alice', total_drive_s: 3720, n_stints: 1, longest_stint_s: 3720, shortest_stint_s: 3720 } },
      total_drive_s: 3720, total_pit_s: 0,
    };
    const plannedVsActual = {
      race: { race_id: 42, race_name: 'Endurance session abc12345', session_id: 'sess-abc123', is_retrospective: true, race_duration_s: 3720, status: 'finished' },
      stints: [{ stint_order: 1, driver_name: 'Alice', planned: { start_s: 0, end_s: 3720, duration_s: 3720 }, actual: { start_s: 0, end_s: 3610, duration_s: 3610, lap_count: 60, best_lap_s: 59.8, mean_lap_s: 60.2, consistency_cv_pct: 1.1, pace_fade_pct: 0.5 }, delta_duration_s: -110 }],
      summary: { total_planned_s: 3720, total_actual_s: 3610, delta_s: -110, driver_deltas: { Alice: { planned_s: 3720, actual_s: 3610, delta_s: -110, stint_count: 1 } } },
    };

    await page.route('**/api/v1/race-strategy/42/summary', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, data: summary, meta: {} }) });
    });
    await page.route('**/api/v1/race-strategy/42/planned-vs-actual', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, data: plannedVsActual, meta: {} }) });
    });

    await page.goto('/app/race-strategy/42/summary');
    await expect(page.getByText('Planned vs Actual Comparison')).toBeVisible();
  });
});

test.describe('Session -> race bridge (endurance-finish)', () => {
  test.beforeEach(async ({ page }) => {
    await page.context().addCookies([{ ...AUTH_COOKIE }]);
    await mockMe(page);
  });

  test('a fully-assigned endurance session shows the create-race action and links to the new race', async ({ page }) => {
    await page.route('**/api/v1/sessions/sess-1', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, data: { session_id: 'sess-1', analysis_json: null }, meta: {} }) });
    });
    await page.route('**/api/v1/sessions/sess-1/stints', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          data: {
            stints: [
              { stint_number: 1, start_lap: 1, end_lap: 30, lap_count: 30, driver_name: 'Alice' },
              { stint_number: 2, start_lap: 32, end_lap: 60, lap_count: 29, driver_name: 'Bob' },
            ],
            pit_threshold_s: 120,
            total_stints: 2,
          },
          meta: {},
        }),
      });
    });
    await page.route('**/api/v1/sessions/sess-1/endurance-race', async (route) => {
      await route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify({ ok: true, data: { race_id: 77 }, meta: {} }) });
    });

    await page.goto('/app/sessions/sess-1');
    const createButton = page.getByRole('button', { name: /create race strategy from this session/i });
    await expect(createButton).toBeVisible();
    await createButton.click();

    await expect(page).toHaveURL(/\/app\/race-strategy\/77$/);
  });
});
