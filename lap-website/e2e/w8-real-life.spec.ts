import { test, expect } from '@playwright/test';
import path from 'node:path';

// MSW-backed. Run with:
//   NEXT_PUBLIC_USE_MSW=1 npm run dev &
//   npx playwright test e2e/w8-real-life.spec.ts
test.describe('W8 — real-life flow (MSW fixture-backed)', () => {
  test.use({ baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:3000' });

  test('history shows GPS badge; session page hides input-driven panels', async ({ page }) => {
    await page.goto('/app/sessions');
    await expect(page.getByRole('columnheader', { name: /source/i })).toBeVisible();
    await expect(page.getByText('GPS').first()).toBeVisible();

    await page.getByRole('row', { name: /franciacorta/i }).click();
    await expect(page.getByRole('heading', { name: /coaching/i })).toBeVisible();
    await expect(page.getByText(/output-based/i)).toBeVisible();
    await expect(page.getByText(/trajectory-only/i)).toBeVisible();
    await expect(page.getByTestId('reconstructed-inputs-summary')).not.toBeVisible();
  });

  test('upload page accepts CSV and shows GPS heuristic badge', async ({ page }) => {
    await page.goto('/app/sessions/upload');
    const input = page.locator('input[type="file"]').first();
    await input.setInputFiles(path.join(__dirname, 'fixtures/mini-rc.csv'));
    await expect(page.getByText('GPS')).toBeVisible();
  });
});
