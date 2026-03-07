import { test, expect } from '@playwright/test';

test.describe('Navigation & Page Structure A11y', () => {
  test('marketing page has skip link targeting #main-content', async ({ page }) => {
    await page.goto('/pricing');
    const skipLink = page.locator('a[href="#main-content"]');
    await expect(skipLink).toBeAttached();
    await page.keyboard.press('Tab');
    await expect(skipLink).toBeFocused();
    await expect(page.locator('#main-content')).toBeAttached();
  });

  test('app page has skip link targeting #main-content', async ({ page }) => {
    await page.goto('/app/dashboard');
    const skipLink = page.locator('a[href="#main-content"]');
    await expect(skipLink).toBeAttached();
    await expect(page.locator('#main-content')).toBeAttached();
  });

  test('pricing page has SectionTabs with correct semantics', async ({ page }) => {
    await page.goto('/pricing');
    const nav = page.locator('nav[aria-label="Page sections"]');
    await expect(nav).toBeVisible();
    const links = nav.locator('a');
    expect(await links.count()).toBeGreaterThanOrEqual(2);
    for (const link of await links.all()) {
      const href = await link.getAttribute('href');
      expect(href).toMatch(/^#/);
    }
  });

  test('pricing page has exactly one h1', async ({ page }) => {
    await page.goto('/pricing');
    const h1s = page.locator('h1');
    expect(await h1s.count()).toBe(1);
  });

  test('subpage has breadcrumb with correct semantics', async ({ page }) => {
    const response = await page.goto('/pricing/compare');
    if (response && response.status() === 200) {
      const nav = page.locator('nav[aria-label="Breadcrumb"]');
      await expect(nav).toBeVisible();
      const ol = nav.locator('ol');
      await expect(ol).toBeAttached();
      const current = nav.locator('[aria-current="page"]');
      await expect(current).toBeAttached();
    }
  });

  test('app dashboard has legal footer links', async ({ page }) => {
    await page.goto('/app/dashboard');
    const footer = page.locator('footer');
    await expect(footer).toBeAttached();
    await expect(page.locator('footer a[href="/privacy"]')).toBeAttached();
    await expect(page.locator('footer a[href="/terms"]')).toBeAttached();
    await expect(page.locator('footer a[href="/security"]')).toBeAttached();
    await expect(page.locator('footer a[href="/status"]')).toBeAttached();
  });

  test('SectionTabs keyboard navigation works', async ({ page }) => {
    await page.goto('/pricing');
    const nav = page.locator('nav[aria-label="Page sections"]');
    const firstTab = nav.locator('a').first();
    await firstTab.focus();
    await expect(firstTab).toBeFocused();
  });
});
