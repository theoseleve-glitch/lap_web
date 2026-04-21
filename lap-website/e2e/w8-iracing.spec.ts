import { test, expect } from '@playwright/test';
import path from 'node:path';

// MSW-backed. Run with:
//   NEXT_PUBLIC_USE_MSW=1 npm run dev &
//   npx playwright test e2e/w8-iracing.spec.ts
test.describe('W8 — iRacing flow (MSW fixture-backed)', () => {
  test.use({ baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:3000' });

  test('history shows iRacing badge; session page reveals input-aware panels', async ({ page }) => {
    await page.goto('/app/sessions');
    await expect(page.getByText('iRacing').first()).toBeVisible();

    await page.getByRole('row', { name: /spa-francorchamps/i }).click();
    await expect(page.getByText(/full fidelity/i)).toBeVisible();
    await expect(page.getByTestId('reconstructed-inputs-summary')).toBeVisible();
    await expect(page.getByText(/output-based/i)).not.toBeVisible();
  });

  test('upload page accepts .ibt and shows iRacing heuristic badge', async ({ page }) => {
    await page.goto('/app/sessions/upload');
    const input = page.locator('input[type="file"]').first();
    await input.setInputFiles(path.join(__dirname, 'fixtures/mini-iracing.ibt'));
    await expect(page.getByText('iRacing')).toBeVisible();
  });
});
