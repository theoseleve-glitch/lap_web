import { test, expect } from '@playwright/test';

const MOCK_CORNER_REPLAY = {
  session_id: 'sess-001',
  track_id: 'track-001',
  has_pedal_data: false,
  has_steering_data: false,
  corners: [
    { corner_id: '1', label: 'Turn 1', lat: 45.005, lon: 9.005, dist_m: 100 },
    { corner_id: '2', label: 'Hairpin', lat: 45.010, lon: 9.010, dist_m: 500 },
    { corner_id: '3', label: 'Chicane', lat: 45.015, lon: 9.015, dist_m: 800 },
  ],
  laps: [
    { lap_number: 1, lap_time_s: 61.0 },
    { lap_number: 2, lap_time_s: 60.5 },
  ],
  traces: {
    '1': {
      lat: Array.from({ length: 50 }, (_, i) => 45.0 + i * 0.0001),
      lon: Array.from({ length: 50 }, (_, i) => 9.0 + i * 0.0001),
      dist_m: Array.from({ length: 50 }, (_, i) => i * 20),
      speed_mps: Array.from({ length: 50 }, () => 18),
      accel_lat: Array.from({ length: 50 }, () => 0),
      accel_lon: Array.from({ length: 50 }, () => 0),
    },
    '2': {
      lat: Array.from({ length: 50 }, (_, i) => 45.0 + i * 0.0001),
      lon: Array.from({ length: 50 }, (_, i) => 9.0 + i * 0.0001),
      dist_m: Array.from({ length: 50 }, (_, i) => i * 20),
      speed_mps: Array.from({ length: 50 }, () => 19),
      accel_lat: Array.from({ length: 50 }, () => 0),
      accel_lon: Array.from({ length: 50 }, () => 0),
    },
  },
  replay_windows: {
    '1': [
      { lap_number: 1, start_idx: 0, end_idx: 30, estimated_duration_s: 4.0 },
      { lap_number: 2, start_idx: 0, end_idx: 30, estimated_duration_s: 3.8 },
    ],
    '2': [
      { lap_number: 1, start_idx: 20, end_idx: 49, estimated_duration_s: 5.0 },
      { lap_number: 2, start_idx: 20, end_idx: 49, estimated_duration_s: 4.8 },
    ],
    '3': [
      { lap_number: 1, start_idx: 35, end_idx: 49, estimated_duration_s: 3.0 },
      { lap_number: 2, start_idx: 35, end_idx: 49, estimated_duration_s: 2.9 },
    ],
  },
  corner_metrics: {
    '1': [
      { lap_number: 1, brake_point_m: 90, entry_speed_mps: 20, apex_speed_mps: 15, exit_speed_mps: 18, time_loss_ms: 50, coaching_hint: null },
    ],
    '2': [
      { lap_number: 1, brake_point_m: 490, entry_speed_mps: 22, apex_speed_mps: 12, exit_speed_mps: 16, time_loss_ms: 80, coaching_hint: 'Brake later' },
    ],
    '3': [
      { lap_number: 1, brake_point_m: 790, entry_speed_mps: 18, apex_speed_mps: 14, exit_speed_mps: 17, time_loss_ms: 40, coaching_hint: null },
    ],
  },
};

// Session detail mock that the session page needs
const MOCK_SESSION_DETAIL = {
  id: 'sess-001',
  date: '2026-02-20',
  track_name: 'Test Track',
  driver_name: 'Test Driver',
  laps: 10,
  best_time: 60.5,
  score: 82.4,
  grade: 'A',
  consistency_score: 21.0,
  pace_score: 22.0,
  execution_score: 19.5,
  robustness_score: 19.9,
};

const MOCK_LAPS = {
  laps: [
    { lap_number: 1, time: 61.0, speed_avg: 78.2, valid: true },
    { lap_number: 2, time: 60.5, speed_avg: 79.1, valid: true },
  ],
};

test.describe('Corner Replay', () => {
  test.beforeEach(async ({ page }) => {
    await page.context().addCookies([
      { name: 'access_token', value: 'test-token', domain: 'localhost', path: '/' },
    ]);

    // Mock session detail
    await page.route('**/api/v1/sessions/sess-001/details', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ok: true, data: MOCK_SESSION_DETAIL, meta: { request_id: 'test-detail' } }),
      });
    });

    // Mock laps
    await page.route('**/api/v1/sessions/sess-001/laps', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ok: true, data: MOCK_LAPS, meta: { request_id: 'test-laps' } }),
      });
    });

    // Mock corner replay batch
    await page.route('**/api/v1/sessions/sess-001/corner-replay', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ok: true, data: MOCK_CORNER_REPLAY, meta: { request_id: 'test-replay' } }),
      });
    });

    // Mock all other session endpoints with generic success
    await page.route('**/api/v1/sessions/sess-001/**', async (route) => {
      const url = route.request().url();
      if (url.includes('/details') || url.includes('/laps') || url.includes('/corner-replay')) {
        return; // handled by specific routes above
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ok: true, data: { points: [], labels: [] }, meta: { request_id: 'test-fallback' } }),
      });
    });
  });

  test('corner replay tab loads and shows controls', async ({ page }) => {
    await page.goto('/app/sessions/sess-001');
    // Click Corners & Coaching tab
    await page.getByRole('button', { name: /Corners/i }).click();
    // Should show corner pills
    await expect(page.getByText('Turn 1')).toBeVisible();
    await expect(page.getByText('Hairpin')).toBeVisible();
  });

  test('mode switching updates UI', async ({ page }) => {
    await page.goto('/app/sessions/sess-001');
    await page.getByRole('button', { name: /Corners/i }).click();
    // Wait for corner replay to load
    await expect(page.getByText('Turn 1')).toBeVisible();
    // Switch to Split mode
    await page.getByText('Split').click();
    // Lap selectors should appear
    await expect(page.getByText('Lap A')).toBeVisible();
    await expect(page.getByText('Lap B')).toBeVisible();
  });

  test('corner pill navigation changes active corner', async ({ page }) => {
    await page.goto('/app/sessions/sess-001');
    await page.getByRole('button', { name: /Corners/i }).click();
    await expect(page.getByText('Turn 1')).toBeVisible();
    // Click Hairpin
    await page.getByText('Hairpin').click();
    // Hairpin pill should be highlighted (has bg-acid-green class)
    const hairpinBtn = page.getByText('Hairpin');
    await expect(hairpinBtn).toHaveClass(/bg-acid-green/);
  });

  test('play/pause button toggles', async ({ page }) => {
    await page.goto('/app/sessions/sess-001');
    await page.getByRole('button', { name: /Corners/i }).click();
    await expect(page.getByText('Turn 1')).toBeVisible();
    const playBtn = page.getByRole('button', { name: 'Play' });
    await expect(playBtn).toBeVisible();
    await playBtn.click();
    // Should now show Pause
    await expect(page.getByRole('button', { name: 'Pause' })).toBeVisible();
  });

  test('shows error for 409 response', async ({ page }) => {
    // Override to return 409
    await page.route('**/api/v1/sessions/sess-001/corner-replay', async (route) => {
      await route.fulfill({
        status: 409,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: false,
          error: { code: 'CONFLICT', message: 'No key corners defined for this track' },
          meta: { request_id: 'test-409' },
        }),
      });
    });
    await page.goto('/app/sessions/sess-001');
    await page.getByRole('button', { name: /Corners/i }).click();
    await expect(page.getByText(/No corners selected/i)).toBeVisible();
  });
});
