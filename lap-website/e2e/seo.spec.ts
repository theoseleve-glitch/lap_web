import { test, expect } from '@playwright/test';

test.describe('SEO meta tags', () => {
  test('pricing page has meta description', async ({ page }) => {
    await page.goto('/pricing');
    const desc = page.locator('meta[name="description"]');
    await expect(desc).toBeAttached();
    const content = await desc.getAttribute('content');
    expect(content!.length).toBeGreaterThanOrEqual(80);
  });

  test('pricing page has og:title and og:description', async ({ page }) => {
    await page.goto('/pricing');
    await expect(page.locator('meta[property="og:title"]')).toBeAttached();
    await expect(page.locator('meta[property="og:description"]')).toBeAttached();
  });

  test('pricing page has og:image', async ({ page }) => {
    await page.goto('/pricing');
    const ogImage = page.locator('meta[property="og:image"]');
    await expect(ogImage).toBeAttached();
    const url = await ogImage.getAttribute('content');
    expect(url).toContain('og');
  });

  test('pricing page has canonical URL', async ({ page }) => {
    await page.goto('/pricing');
    const canonical = page.locator('link[rel="canonical"]');
    await expect(canonical).toBeAttached();
    const href = await canonical.getAttribute('href');
    expect(href).toContain('/pricing');
  });

  test('pricing page has JSON-LD structured data', async ({ page }) => {
    await page.goto('/pricing');
    const scripts = page.locator('script[type="application/ld+json"]');
    expect(await scripts.count()).toBeGreaterThanOrEqual(1);
  });

  test('app dashboard has noindex', async ({ page }) => {
    await page.goto('/app/dashboard');
    const robots = page.locator('meta[name="robots"]');
    await expect(robots).toBeAttached();
    const content = await robots.getAttribute('content');
    expect(content).toContain('noindex');
  });

  test('product page has meta description', async ({ page }) => {
    await page.goto('/product');
    const desc = page.locator('meta[name="description"]');
    await expect(desc).toBeAttached();
  });
});
