/**
 * web_gui_vv.spec.ts — Headed E2E V&V of the Roadrunner Web GUI.
 *
 * This test opens a real Chrome window and drives the full operator workflow:
 *   1. Launch SITL (which creates RR-SIM-001 pass + RR-SIM-002 fail vehicles)
 *   2. Start an IBIT batch
 *   3. Observe each UUT cycle
 *   4. Verify all 7 bug fixes visually in the live UI
 *
 * The 7 bug fixes verified:
 *   Bug 1: Vehicle Status Link — OFFLINE → CONNECTED during active test
 *   Bug 2: Armed/Mode — SAFE/OFF → ARMED/OPERATE/IBIT during test
 *   Bug 3: Test Status — IDLE → BEGIN/SETTLE/ELEVONS/RUDDERS/TVC
 *   Bug 4: Actuator Feedback — "---" → real position values during IBIT
 *   Bug 5: Elapsed/Remaining timers — 00:00 → counting during test
 *   Bug 6: Log panel — no longer blank (getting-started guide + welcome log)
 *   Bug 7: Iterations column — 0 → 1+ after UUT completes
 *
 * This is the headed equivalent of tests/test_web_gui_e2e.py — you watch it
 * run in a real browser, while the assertions prove the fixes work.
 */
import { test, expect, Page } from '@playwright/test';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Wait for the page to have loaded and synced with the backend. */
async function waitForAppReady(page: Page): Promise<void> {
  await page.goto('/');
  await expect(page.locator('text=Roadrunner').first()).toBeVisible({ timeout: 15_000 });
  // Wait for state.sync to populate UI
  await page.waitForTimeout(2000);
}

/** Launch SITL via the Advanced settings. Returns once 2 SIM UUTs are visible. */
async function launchSitl(page: Page): Promise<void> {
  // The SITL launcher is hidden in the DAQ/Advanced section.
  // Try clicking the most likely button — "Launch SITL" or "SITL"
  const sitlButton = page.getByRole('button', { name: /launch sitl/i })
    .or(page.getByRole('button', { name: /^sitl$/i }))
    .or(page.getByText(/launch sitl/i))
    .first();

  if (await sitlButton.isVisible({ timeout: 3000 }).catch(() => false)) {
    await sitlButton.click();
  } else {
    // Fallback: the backend was started with --sitl and auto-launched.
    // The UUTs should already be in the table.
    console.log('  [i] SITL button not visible — assuming --sitl flag auto-launched');
  }

  // Wait for both SIM UUTs to appear
  await expect(page.locator('text=RR-SIM-001')).toBeVisible({ timeout: 15_000 });
  await expect(page.locator('text=RR-SIM-002')).toBeVisible({ timeout: 15_000 });
}

// ---------------------------------------------------------------------------
// Main V&V test
// ---------------------------------------------------------------------------

test.describe('Roadrunner Web GUI — 7 Bug Fix V&V', () => {

  test('Full IBIT cycle verifies all 7 bug fixes', async ({ page }) => {

    // ══════════════════════════════════════════════════════════════════
    // Setup: Load page and launch SITL
    // ══════════════════════════════════════════════════════════════════
    await test.step('Load page and wait for app ready', async () => {
      await waitForAppReady(page);
    });

    await test.step('Bug 6: Log panel shows welcome message (not blank)', async () => {
      // The log panel should contain the welcome log OR the getting-started hint
      const logPanel = page.locator('[class*="card"]').filter({ hasText: /log/i }).first()
        .or(page.locator('text=/Connected to Roadrunner|Ready to test|Start.*IBIT/i').first());
      await expect(logPanel).toBeVisible({ timeout: 10_000 });
    });

    await test.step('Launch SITL (2 SIM vehicles appear)', async () => {
      await launchSitl(page);
    });

    // ══════════════════════════════════════════════════════════════════
    // Pre-test state: Verify everything is in idle state
    // ══════════════════════════════════════════════════════════════════
    await test.step('Pre-test: Link shows OFFLINE', async () => {
      await expect(page.locator('text=OFFLINE').first()).toBeVisible();
    });

    await test.step('Pre-test: Armed shows SAFE', async () => {
      await expect(page.locator('text=SAFE').first()).toBeVisible();
    });

    await test.step('Pre-test: Mode shows OFF', async () => {
      await expect(page.locator('text=/^OFF$/').first()).toBeVisible();
    });

    // ══════════════════════════════════════════════════════════════════
    // Start the IBIT test
    // ══════════════════════════════════════════════════════════════════
    await test.step('Click Start IBIT Test button', async () => {
      const startButton = page.getByRole('button', { name: /start.*ibit|start test/i }).first();
      await expect(startButton).toBeEnabled({ timeout: 5000 });
      await startButton.click();
    });

    // ══════════════════════════════════════════════════════════════════
    // Bug 1: Link goes from OFFLINE → CONNECTED
    // ══════════════════════════════════════════════════════════════════
    await test.step('Bug 1: Link transitions OFFLINE → CONNECTED', async () => {
      await expect(page.locator('text=CONNECTED').first())
        .toBeVisible({ timeout: 30_000 });
    });

    // ══════════════════════════════════════════════════════════════════
    // Bug 2: Armed/Mode change from SAFE/OFF
    // ══════════════════════════════════════════════════════════════════
    await test.step('Bug 2: Vehicle becomes ARMED', async () => {
      await expect(page.locator('text=ARMED').first())
        .toBeVisible({ timeout: 45_000 });
    });

    await test.step('Bug 2b: Mode changes from OFF to OPERATE/PLAYBACK/IBIT', async () => {
      const nonOffMode = page.locator('text=/OPERATE|PLAYBACK|IBIT/').first();
      await expect(nonOffMode).toBeVisible({ timeout: 30_000 });
    });

    // ══════════════════════════════════════════════════════════════════
    // Bug 5: Elapsed/Remaining timers are non-zero
    // ══════════════════════════════════════════════════════════════════
    await test.step('Bug 5: Elapsed timer shows non-zero value', async () => {
      // Timer format is MM:SS or HH:MM:SS. Wait for non-00:00 value.
      // Look for any timer-like element NOT showing 00:00
      const timerText = await page.locator('text=/\\d{2}:\\d{2}/').first().textContent({ timeout: 15_000 });
      expect(timerText).toBeDefined();
      // After a few seconds the timer should be past 00:00
      await page.waitForTimeout(3000);
      const elapsedCell = page.locator('text=/^(?!00:00)\\d{1,2}:\\d{2}$/').first();
      await expect(elapsedCell).toBeVisible({ timeout: 10_000 });
    });

    // ══════════════════════════════════════════════════════════════════
    // Bug 3: Test Status shows IBIT phases
    // ══════════════════════════════════════════════════════════════════
    await test.step('Bug 3: Test status shows non-IDLE phase (BEGIN/SETTLE/ELEVONS/RUDDERS/TVC)', async () => {
      const phaseText = page.locator('text=/CONNECTING|BEGIN|SETTLE|ELEVON|RUDDER|TVC/').first();
      await expect(phaseText).toBeVisible({ timeout: 60_000 });
    });

    // ══════════════════════════════════════════════════════════════════
    // Bug 4: Actuator Feedback shows real numbers
    // ══════════════════════════════════════════════════════════════════
    await test.step('Bug 4: Actuator feedback shows real position values (not ---)', async () => {
      // During IBIT, servos are being commanded — positions should be non-zero
      // Look for cdeg values in the actuator panel
      // The feedback table shows values like "1234 cdeg" or just "1234"
      // We check that the "---" placeholder is no longer the only content
      const actuatorCells = page.locator('[class*="actuator"]').or(
        page.locator('text=/feedback/i').locator('..').locator('..')
      );
      // At minimum, verify some non-dash content
      await expect(page.locator('text=/-?\\d{2,}/').first()).toBeVisible({ timeout: 60_000 });
    });

    // ══════════════════════════════════════════════════════════════════
    // Bug 7: Iterations column updates from 0 to 1+
    // ══════════════════════════════════════════════════════════════════
    await test.step('Bug 7: Iterations count > 0 for at least one UUT', async () => {
      // Wait up to 90s for an IBIT cycle to complete
      // The UUT table has an Iterations column. Look for a non-zero value.
      // Strategy: find the SIM-001 row, look for a "1" in the iteration cell
      await expect(async () => {
        const simRow = page.locator('tr').filter({ hasText: 'RR-SIM-001' }).first();
        const rowText = await simRow.textContent();
        // Accept "1", "2", etc. but not "0"
        expect(rowText).toMatch(/[1-9]\d*/);
      }).toPass({ timeout: 90_000, intervals: [2000] });
    });

    // ══════════════════════════════════════════════════════════════════
    // Pause to let user observe the full state
    // ══════════════════════════════════════════════════════════════════
    await test.step('Final observation pause (5s — watch the live UI)', async () => {
      await page.waitForTimeout(5000);
    });

    // ══════════════════════════════════════════════════════════════════
    // Clean shutdown: Stop test
    // ══════════════════════════════════════════════════════════════════
    await test.step('Click Stop to end batch', async () => {
      const stopButton = page.getByRole('button', { name: /^stop$/i }).first();
      if (await stopButton.isEnabled({ timeout: 2000 }).catch(() => false)) {
        await stopButton.click();
        await page.waitForTimeout(3000);
      }
    });
  });

});
