import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright E2E test configuration for the LAP telemetry web app.
 *
 * - baseURL: http://localhost:3000 (Next.js dev server)
 * - webServer: starts `npm run dev` automatically before tests
 * - Projects: chromium only (for speed)
 * - Retries: 1 on CI, 0 locally
 * - Reporter: html
 */
export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: 'html',

  use: {
    baseURL: 'http://localhost:3000',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],

  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:3000',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
