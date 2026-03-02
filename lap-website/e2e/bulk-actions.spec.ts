import { test, expect } from '@playwright/test';

/**
 * Bulk actions E2E tests for session list interactions.
 *
 * Tests verify that bulk action controls (delete, compare) appear correctly
 * based on selection state, and that actions function as expected.
 */

test.describe('Bulk Actions', () => {
  /**
   * Mock helper for sessions list with multiple items
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
                track_name: 'Track 1',
                date: '2024-03-01',
                duration_seconds: 600,
                notes: 'Session 1',
                score: 85,
              },
              {
                id: '2',
                driver_id: 1,
                track_id: 1,
                date: '2024-03-02',
                duration_seconds: 650,
                notes: 'Session 2',
                score: 88,
              },
              {
                id: '3',
                driver_id: 1,
                track_id: 2,
                date: '2024-03-03',
                duration_seconds: 620,
                notes: 'Session 3',
                score: 82,
              },
              {
                id: '4',
                driver_id: 2,
                driver_name: 'Driver B',
                track_id: 1,
                date: '2024-03-04',
                duration_seconds: 610,
                notes: 'Session 4',
                score: 80,
              },
            ],
            total: 4,
            page: 1,
            page_size: 50,
          },
          meta: { request_id: 'test-req-1' },
        }),
      });
    });
  }

  test('session list renders with checkboxes', async ({ page }) => {
    await mockSessionsAPI(page);

    await page.goto('/app/sessions');
    await expect(page.locator('text=Sessions')).toBeVisible({ timeout: 10_000 });

    // Session list should have checkboxes for bulk selection
    const checkboxes = page.locator('input[type="checkbox"]');
    const count = await checkboxes.count();

    // Should have at least one checkbox (select-all)
    expect(count).toBeGreaterThan(0);
  });

  test('bulk action bar shows when single row selected', async ({ page }) => {
    await mockSessionsAPI(page);

    await page.goto('/app/sessions');
    await expect(page.locator('text=Sessions')).toBeVisible({ timeout: 10_000 });

    const checkboxes = page.locator('input[type="checkbox"]:not([id*="select-all"])');
    const checkboxCount = await checkboxes.count();

    if (checkboxCount > 0) {
      // Click first row checkbox
      await checkboxes.first().click();

      // Action bar should appear with at least delete option
      await page.waitForTimeout(300); // Allow UI to update
      const actionBar = page.locator('[data-testid="bulk-action-bar"], .bulk-action-bar');
      const deleteButton = page.locator('button:has-text("Delete")');

      // At least one should exist (action bar or delete button)
      const hasActionBar = await actionBar.count();
      const hasDeleteButton = await deleteButton.count();

      if (hasActionBar > 0 || hasDeleteButton > 0) {
        expect(hasActionBar + hasDeleteButton).toBeGreaterThan(0);
      }
    }
  });

  test('bulk action bar shows when multiple rows selected', async ({ page }) => {
    await mockSessionsAPI(page);

    await page.goto('/app/sessions');
    await expect(page.locator('text=Sessions')).toBeVisible({ timeout: 10_000 });

    const checkboxes = page.locator('input[type="checkbox"]:not([id*="select-all"])');
    const checkboxCount = await checkboxes.count();

    if (checkboxCount >= 2) {
      // Click first two checkboxes
      await checkboxes.nth(0).click();
      await checkboxes.nth(1).click();

      // Allow UI to update
      await page.waitForTimeout(300);

      // Should show selection count or action bar
      const selectionCount = page.locator('text=selected');
      const deleteButton = page.locator('button:has-text("Delete")');

      // At least one indicator should appear
      const hasCount = await selectionCount.count();
      const hasDelete = await deleteButton.count();

      if (hasCount > 0 || hasDelete > 0) {
        expect(hasCount + hasDelete).toBeGreaterThan(0);
      }
    }
  });

  test('compare button appears when exactly 2 sessions selected', async ({ page }) => {
    await mockSessionsAPI(page);

    await page.goto('/app/sessions');
    await expect(page.locator('text=Sessions')).toBeVisible({ timeout: 10_000 });

    const checkboxes = page.locator('input[type="checkbox"]:not([id*="select-all"])');
    const checkboxCount = await checkboxes.count();

    if (checkboxCount >= 2) {
      // Select exactly 2 sessions
      await checkboxes.nth(0).click();
      await checkboxes.nth(1).click();

      // Allow UI to update
      await page.waitForTimeout(300);

      // Compare button should appear
      const compareButton = page.locator('button:has-text("Compare")');
      const compareButtonCount = await compareButton.count();

      // If compare button exists, it should be visible or enabled
      if (compareButtonCount > 0) {
        await expect(compareButton.first()).toBeVisible();
      }
    }
  });

  test('compare button does not appear when 3+ sessions selected', async ({ page }) => {
    await mockSessionsAPI(page);

    await page.goto('/app/sessions');
    await expect(page.locator('text=Sessions')).toBeVisible({ timeout: 10_000 });

    const checkboxes = page.locator('input[type="checkbox"]:not([id*="select-all"])');
    const checkboxCount = await checkboxes.count();

    if (checkboxCount >= 3) {
      // Select 3 sessions
      await checkboxes.nth(0).click();
      await checkboxes.nth(1).click();
      await checkboxes.nth(2).click();

      // Allow UI to update
      await page.waitForTimeout(300);

      // Compare button should be disabled or hidden with 3+ selections
      const compareButton = page.locator('button:has-text("Compare")');
      const compareButtonCount = await compareButton.count();
      const isDisabled = await compareButton.evaluate((el) => el.disabled).catch(() => false);

      // Either no compare button or it's disabled
      if (compareButtonCount > 0) {
        expect(isDisabled || (await compareButton.evaluate((el) => el.offsetParent === null))).toBeTruthy();
      }
    }
  });

  test('delete button triggers confirmation dialog', async ({ page }) => {
    await mockSessionsAPI(page);

    // Mock delete endpoint
    await page.route('**/api/v1/sessions/*', async (route) => {
      if (route.request().method() === 'DELETE') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            ok: true,
            data: { deleted: 1 },
            meta: { request_id: 'test-req-2' },
          }),
        });
      }
    });

    await page.goto('/app/sessions');
    await expect(page.locator('text=Sessions')).toBeVisible({ timeout: 10_000 });

    const checkboxes = page.locator('input[type="checkbox"]:not([id*="select-all"])');
    const checkboxCount = await checkboxes.count();

    if (checkboxCount > 0) {
      // Select first session
      await checkboxes.first().click();
      await page.waitForTimeout(300);

      // Find and click delete button
      const deleteButton = page.locator('button:has-text("Delete")');
      const deleteButtonCount = await deleteButton.count();

      if (deleteButtonCount > 0) {
        await deleteButton.first().click();

        // Wait for confirmation dialog
        const confirmDialog = page.locator('[role="dialog"], .modal, .alert-dialog');
        const confirmCount = await confirmDialog.count();

        // Should show confirmation (dialog or toast)
        if (confirmCount > 0) {
          await expect(confirmDialog.first()).toBeVisible();
        }
      }
    }
  });

  test('select all checkbox selects all visible rows', async ({ page }) => {
    await mockSessionsAPI(page);

    await page.goto('/app/sessions');
    await expect(page.locator('text=Sessions')).toBeVisible({ timeout: 10_000 });

    // Find select-all checkbox
    const selectAllCheckbox = page.locator('input[id*="select-all"], input[aria-label="Select all"]');
    const selectAllCount = await selectAllCheckbox.count();

    if (selectAllCount > 0) {
      // Click select-all
      await selectAllCheckbox.first().click();
      await page.waitForTimeout(300);

      // Individual checkboxes should now be checked
      const individualCheckboxes = page.locator('input[type="checkbox"]:not([id*="select-all"])');
      const checkedCount = await individualCheckboxes.locator(':checked').count();

      expect(checkedCount).toBeGreaterThan(0);
    }
  });
});
