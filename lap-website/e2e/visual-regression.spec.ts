/**
 * Visual regression tests using Playwright screenshot diffs.
 *
 * Captures key marketing + app screens and compares against baselines.
 * Run: npx playwright test e2e/visual-regression.spec.ts --update-snapshots (first run)
 * Run: npx playwright test e2e/visual-regression.spec.ts (subsequent runs)
 *
 * CI: gate merges on significant diffs (threshold: 0.1%).
 */

import { test, expect } from '@playwright/test';

const VIEWPORT = { width: 1280, height: 720 };
const MOBILE_VIEWPORT = { width: 375, height: 812 };

// Marketing pages
const MARKETING_PAGES = [
  { name: 'home', path: '/' },
  { name: 'product', path: '/product' },
  { name: 'pricing', path: '/pricing' },
  { name: 'customers', path: '/customers' },
  { name: 'privacy', path: '/privacy' },
];

// App pages (require auth stub or static render)
const APP_PAGES = [
  { name: 'sessions-empty', path: '/app/sessions' },
  { name: 'login', path: '/login' },
  { name: 'register', path: '/register' },
];

test.describe('Visual regression — desktop', () => {
  test.use({ viewport: VIEWPORT });

  for (const page of MARKETING_PAGES) {
    test(`marketing/${page.name}`, async ({ page: p }) => {
      await p.goto(page.path, { waitUntil: 'networkidle' });
      // Wait for fonts and animations to settle
      await p.waitForTimeout(1500);
      await expect(p).toHaveScreenshot(`desktop-${page.name}.png`, {
        maxDiffPixelRatio: 0.001,
        fullPage: false,
      });
    });
  }

  for (const page of APP_PAGES) {
    test(`app/${page.name}`, async ({ page: p }) => {
      await p.goto(page.path, { waitUntil: 'networkidle' });
      await p.waitForTimeout(1000);
      await expect(p).toHaveScreenshot(`desktop-${page.name}.png`, {
        maxDiffPixelRatio: 0.001,
        fullPage: false,
      });
    });
  }
});

test.describe('Visual regression — mobile', () => {
  test.use({ viewport: MOBILE_VIEWPORT });

  for (const page of MARKETING_PAGES.slice(0, 3)) {
    test(`marketing/${page.name}`, async ({ page: p }) => {
      await p.goto(page.path, { waitUntil: 'networkidle' });
      await p.waitForTimeout(1500);
      await expect(p).toHaveScreenshot(`mobile-${page.name}.png`, {
        maxDiffPixelRatio: 0.002,
        fullPage: false,
      });
    });
  }
});
