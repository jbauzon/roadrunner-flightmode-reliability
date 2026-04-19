// @ts-check
import { defineConfig } from '@playwright/test';

/**
 * Headed V&V configuration for Roadrunner Web GUI.
 *
 * This runs a REAL browser window you watch. The test drives the full
 * operator flow: launches SITL, starts an IBIT batch, and verifies all
 * 7 bug fixes against the live UI.
 *
 * Run with:
 *   npm run test:headed          # watch a single window
 *   npm run test:ui              # interactive Playwright Inspector
 */
export default defineConfig({
  testDir: './',
  testMatch: /.*\.spec\.ts/,
  timeout: 180_000,       // 3 min per test (IBIT cycle takes ~60s)
  expect: { timeout: 30_000 },

  fullyParallel: false,   // Only one test at a time (shared backend)
  workers: 1,
  retries: 0,
  reporter: [
    ['list'],
    ['html', { outputFolder: 'playwright-report', open: 'never' }],
  ],

  use: {
    baseURL: 'http://localhost:18890',
    headless: false,              // HEADED MODE — you watch it run
    viewport: { width: 1920, height: 1080 },
    actionTimeout: 10_000,
    navigationTimeout: 20_000,
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    trace: 'retain-on-failure',

    // Slow down so a human can follow
    launchOptions: {
      slowMo: 250,
      args: ['--window-position=100,50'],
    },
  },

  projects: [
    {
      name: 'chromium-headed',
      use: {
        browserName: 'chromium',
        channel: 'chrome',
      },
    },
  ],
});
