import { test, expect } from '@playwright/test';

/**
 * Upload / Analyze wizard E2E tests.
 *
 * The Analyze page (/app/analyze) is a 3-step wizard:
 *   Step 1 (Select Data):  File browser + drag-drop upload zone
 *   Step 2 (Configure):    Session type, driver, track, kart selectors
 *   Step 3 (Analyze):      Progress bar + status polling
 *
 * The page fetches from /api/v1/files/list (step 1), /api/v1/drivers,
 * /api/v1/tracks, /api/v1/karts (step 2), and /api/v1/ingest/start +
 * /api/v1/ingest/status/:id (step 3). All are mocked via page.route().
 */
test.describe('Upload wizard', () => {
  test.beforeEach(async ({ page }) => {
    // Set auth cookie so the app layout renders without redirect issues
    await page.context().addCookies([
      {
        name: 'access_token',
        value: 'test-token',
        domain: 'localhost',
        path: '/',
      },
    ]);

    // Mock file list API for step 1
    await page.route('**/api/v1/files/list', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          data: {
            files: [
              { name: 'session_2026-02-20.csv', size: 2_450_000, modified: '2026-02-20' },
              { name: 'session_2026-02-15.csv', size: 1_800_000, modified: '2026-02-15' },
            ],
          },
          meta: { request_id: 'test-files' },
        }),
      });
    });

    // Mock drivers/tracks/karts for step 2
    await page.route('**/api/v1/drivers', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          data: {
            drivers: [
              { driver_id: 1, driver_name: 'Max Speed' },
              { driver_id: 2, driver_name: 'Ana Brakes' },
            ],
          },
          meta: { request_id: 'test-drivers' },
        }),
      });
    });

    await page.route('**/api/v1/tracks', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          data: {
            tracks: [
              { track_id: 1, track_name: 'Karting Arena' },
              { track_id: 2, track_name: 'Circuit de Barcelona' },
            ],
          },
          meta: { request_id: 'test-tracks' },
        }),
      });
    });

    await page.route('**/api/v1/karts', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          data: { karts: [{ id: 1, name: 'Kart #7' }] },
          meta: { request_id: 'test-karts' },
        }),
      });
    });
  });

  test('step 1: file selection is visible and lists server files', async ({ page }) => {
    await page.goto('/app/analyze');

    // Page header
    await expect(page.getByText('New Analysis')).toBeVisible();

    // Step indicator shows step 1 as active
    await expect(page.getByText('Select Data')).toBeVisible();

    // Data source heading
    await expect(page.getByText('Data Source')).toBeVisible();

    // Upload button is present
    await expect(page.getByRole('button', { name: 'Upload CSV' })).toBeVisible();

    // Server files are listed
    await expect(page.getByText('session_2026-02-20.csv')).toBeVisible();
    await expect(page.getByText('session_2026-02-15.csv')).toBeVisible();

    // "Next: Configure" button is disabled until a file is selected
    const nextButton = page.getByRole('button', { name: 'Next: Configure' });
    await expect(nextButton).toBeVisible();
    await expect(nextButton).toBeDisabled();
  });

  test('step 1 -> step 2: select file and advance to configure', async ({ page }) => {
    await page.goto('/app/analyze');

    // Select first file from the server list
    await page.getByText('session_2026-02-20.csv').click();

    // Selection indicator appears
    await expect(page.getByText('Selected: session_2026-02-20.csv')).toBeVisible();

    // Next button becomes enabled
    const nextButton = page.getByRole('button', { name: 'Next: Configure' });
    await expect(nextButton).toBeEnabled();

    // Advance to step 2
    await nextButton.click();

    // Step 2 content: "Session Configuration"
    await expect(page.getByText('Session Configuration')).toBeVisible();

    // File name shown
    await expect(page.getByText('session_2026-02-20.csv')).toBeVisible();

    // Dropdowns for driver, track, kart, session type are visible
    await expect(page.getByText('Session Type')).toBeVisible();
    await expect(page.getByText('Driver')).toBeVisible();
    await expect(page.getByText('Track')).toBeVisible();
    await expect(page.getByText('Kart')).toBeVisible();

    // Start analysis button
    await expect(page.getByRole('button', { name: 'Start Analysis' })).toBeVisible();
  });

  test('step 2 -> step 3: start analysis shows progress', async ({ page }) => {
    // Mock ingest start
    await page.route('**/api/v1/ingest/start', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          data: { job_id: 'job-abc-123' },
          meta: { request_id: 'test-ingest' },
        }),
      });
    });

    // Mock ingest status polling (return processing)
    await page.route('**/api/v1/ingest/status/job-abc-123', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          data: {
            job_id: 'job-abc-123',
            status: 'processing',
            progress: 45,
            message: 'Processing GPS data...',
          },
          meta: { request_id: 'test-status' },
        }),
      });
    });

    await page.goto('/app/analyze');

    // Step 1: select file
    await page.getByText('session_2026-02-20.csv').click();
    await page.getByRole('button', { name: 'Next: Configure' }).click();

    // Step 2: click Start Analysis
    await page.getByRole('button', { name: 'Start Analysis' }).click();

    // Step 3: progress view renders
    await expect(page.getByText('Analyzing...')).toBeVisible();
  });
});
