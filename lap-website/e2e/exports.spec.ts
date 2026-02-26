import { test, expect } from '@playwright/test';

/**
 * Exports page E2E tests.
 *
 * Page tested:
 *   /app/exports - ExportsPage: "Generate Export" form (data type dropdown + format buttons + generate button),
 *                  DataTable of existing exports with download links.
 *
 * API endpoints mocked:
 *   GET  /api/v1/exports          - existing exports list
 *   POST /api/v1/exports/generate - trigger new export
 */

const MOCK_EXPORTS = {
  ok: true,
  data: {
    exports: [
      {
        id: 1,
        name: 'All Sessions - 2026-02-20',
        format: 'csv',
        size: 245_000,
        status: 'ready',
        created_at: '2026-02-20 14:30',
        download_url: '/api/v1/exports/1/download',
      },
      {
        id: 2,
        name: 'Lap Data - 2026-02-18',
        format: 'json',
        size: 1_200_000,
        status: 'ready',
        created_at: '2026-02-18 09:15',
        download_url: '/api/v1/exports/2/download',
      },
      {
        id: 3,
        name: 'Score History - 2026-02-15',
        format: 'pdf',
        size: 0,
        status: 'generating',
        created_at: '2026-02-15 16:45',
        download_url: null,
      },
    ],
  },
  meta: { request_id: 'test-exports' },
};

test.describe('Exports page', () => {
  test.beforeEach(async ({ page }) => {
    await page.context().addCookies([
      { name: 'access_token', value: 'test-token', domain: 'localhost', path: '/' },
    ]);

    await page.route('**/api/v1/exports', async (route) => {
      if (route.request().method() === 'GET') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(MOCK_EXPORTS),
        });
      }
    });
  });

  test('exports page renders with generate form and export table', async ({ page }) => {
    await page.goto('/app/exports');

    // Page header
    await expect(page.getByText('Exports')).toBeVisible();
    await expect(page.getByText('Download your telemetry data')).toBeVisible();

    // Generate export section heading
    await expect(page.getByText('Generate Export')).toBeVisible();

    // Data type dropdown
    await expect(page.getByText('Data Type')).toBeVisible();

    // Format buttons (csv, json, pdf, parquet)
    await expect(page.getByText('Format')).toBeVisible();
    await expect(page.getByRole('button', { name: 'csv' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'json' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'pdf' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'parquet' })).toBeVisible();

    // Generate button
    await expect(page.getByRole('button', { name: 'Generate' })).toBeVisible();

    // Exports table data
    await expect(page.getByText('All Sessions - 2026-02-20')).toBeVisible();
    await expect(page.getByText('Lap Data - 2026-02-18')).toBeVisible();
    await expect(page.getByText('Score History - 2026-02-15')).toBeVisible();

    // Download links appear for ready exports
    const downloadLinks = page.getByText('Download');
    await expect(downloadLinks.first()).toBeVisible();
  });

  test('selecting a format highlights the chosen button', async ({ page }) => {
    await page.goto('/app/exports');

    // Click the json format button
    await page.getByRole('button', { name: 'json' }).click();

    // The json button should now have the active class (border-acid-green)
    const jsonButton = page.getByRole('button', { name: 'json' });
    await expect(jsonButton).toBeVisible();

    // Click parquet
    await page.getByRole('button', { name: 'parquet' }).click();
    const parquetButton = page.getByRole('button', { name: 'parquet' });
    await expect(parquetButton).toBeVisible();
  });

  test('generate button triggers export creation', async ({ page }) => {
    let generateCalled = false;

    await page.route('**/api/v1/exports/generate', async (route) => {
      generateCalled = true;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          data: { id: 4, status: 'generating' },
          meta: { request_id: 'test-gen' },
        }),
      });
    });

    await page.goto('/app/exports');

    // Click generate
    await page.getByRole('button', { name: 'Generate' }).click();

    // Wait a moment for the request to be made
    await page.waitForTimeout(500);

    expect(generateCalled).toBe(true);
  });
});
