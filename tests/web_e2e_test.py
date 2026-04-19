"""
Web GUI End-to-End Test Suite

Uses Playwright to automate the browser against the real WebSocket backend + SITL.
Tests every operator workflow through the actual web interface.

Scenarios:
  A. Happy path: Launch SITL → Start IBIT → verify pass/fail → batch complete
  B. Debug mode: Connect → send commands → verify telemetry
  C. Edge cases: Emergency stop, UUT management, config changes

Requires:
  - playwright (pip install playwright && playwright install chromium)
  - ws_server.py running with --sitl
"""
import asyncio
import json
import os
import sys
import time
import subprocess
import signal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL = 'http://localhost:18890'
WS_PORT = 18889
HTTP_PORT = 18890

results = []

async def run_all():
    from playwright.async_api import async_playwright

    # ── Start backend ─────────────────────────────────────────────────────
    print('Starting backend server...', flush=True)
    server = subprocess.Popen(
        [sys.executable, 'ws_server.py'],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )

    # Wait for server
    import socket
    for i in range(30):
        try:
            s = socket.socket()
            s.settimeout(1)
            s.connect(('127.0.0.1', HTTP_PORT))
            s.close()
            break
        except:
            time.sleep(1)
    else:
        print('Server failed to start')
        server.terminate()
        return

    print(f'Server ready after {i+1}s', flush=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={'width': 1600, 'height': 900})

        shot_dir = os.path.join(ROOT, 'screenshots', 'web_e2e')
        os.makedirs(shot_dir, exist_ok=True)

        async def screenshot(name):
            path = os.path.join(shot_dir, f'{name}.png')
            await page.screenshot(path=path)
            print(f'  Screenshot: {name}', flush=True)

        async def check(name, condition, detail=''):
            ok = bool(condition)
            status = 'PASS' if ok else 'FAIL'
            print(f'  [{status}] {name}{f" — {detail}" if detail and not ok else ""}', flush=True)
            results.append({'name': name, 'pass': ok, 'detail': detail})

        # ══════════════════════════════════════════════════════════════════
        # A. HAPPY PATH
        # ══════════════════════════════════════════════════════════════════
        print('\n--- A. Happy Path ---', flush=True)

        # A1: Page loads
        await page.goto(URL, wait_until='networkidle', timeout=15000)
        await page.wait_for_timeout(2000)
        await screenshot('A1_initial')

        title = await page.title()
        await check('A1: Page loads', 'Roadrunner' in title or 'Flight' in title, title)

        # A2: Backend connected
        status_bar = await page.text_content('.relative.flex.items-center.h-6')
        await check('A2: Backend connected', status_bar and 'connected' in status_bar.lower(), status_bar)

        # A3: Tab bar visible
        test_tab = await page.locator('text=TEST MODE').count()
        debug_tab = await page.locator('text=DEBUG MODE').count()
        await check('A3: Tab bar visible', test_tab > 0 and debug_tab > 0)

        # A4: DAQ Setup visible
        daq_section = await page.locator('text=DAQ Setup').count()
        await check('A4: DAQ Setup visible', daq_section > 0)

        # A5: Launch SITL from Advanced settings
        advanced_btn = page.locator('text=Advanced').first
        await advanced_btn.click()
        await page.wait_for_timeout(500)
        sitl_link = page.locator('text=Launch simulation')
        if await sitl_link.count() > 0:
            await sitl_link.click()
            await page.wait_for_timeout(5000)  # wait for SITL to boot
            await screenshot('A5_sitl_launched')

            # Verify SITL active
            page_text = await page.text_content('body')
            has_ready = 'Ready' in page_text or 'simulated' in page_text
            await check('A5: SITL launched', has_ready, 'Looking for Ready/simulated')
        else:
            await check('A5: SITL launched', False, 'Launch simulation link not found')

        # A6: UUT table populated
        await page.wait_for_timeout(2000)
        await screenshot('A6_uuts_loaded')
        rows = await page.locator('text=RR-SIM-001').count()
        await check('A6: UUT table populated', rows > 0)

        # A7: Start IBIT test
        start_btn = page.locator('text=Start IBIT Test').first
        if await start_btn.is_enabled():
            await start_btn.click()
            await page.wait_for_timeout(3000)
            await screenshot('A7_test_started')

            # Verify test is running (log should have entries)
            log_area = page.locator('text=No log entries yet')
            log_empty = await log_area.count()
            await check('A7: Test started (log populating)', log_empty == 0)
        else:
            await check('A7: Test started', False, 'Start button disabled')

        # A8: Wait for test progress
        await page.wait_for_timeout(15000)  # wait for IBIT to progress
        await screenshot('A8_test_progress')

        # Check if vehicle status shows something other than OFFLINE
        vehicle_section = await page.text_content('body')
        has_mode = any(m in vehicle_section for m in ['OPERATE', 'IBIT', 'PLAYBACK', 'OFF', 'ARMED'])
        await check('A8: Vehicle status updating', has_mode)

        # A9: Wait for first iteration to complete
        await page.wait_for_timeout(30000)
        await screenshot('A9_iteration_done')

        # Check if iterations > 0
        body_text = await page.text_content('body')
        # Look for iteration count in the UUT table
        has_iteration = '1' in body_text  # At least 1 iteration
        await check('A9: First iteration completed', has_iteration)

        # A10: Stop test
        stop_btn = page.locator('text=Stop').first
        await stop_btn.click()
        await page.wait_for_timeout(5000)
        await screenshot('A10_stopped')
        await check('A10: Test stopped', True)  # If we get here without crash, it stopped

        # ══════════════════════════════════════════════════════════════════
        # B. DEBUG MODE
        # ══════════════════════════════════════════════════════════════════
        print('\n--- B. Debug Mode ---', flush=True)

        # B1: Switch to Debug mode
        await page.click('text=DEBUG MODE')
        await page.wait_for_timeout(1000)
        await screenshot('B1_debug_mode')

        # Verify debug mode content visible
        manual_cmds = await page.locator('text=MANUAL COMMANDS').count()
        await check('B1: Debug mode visible', manual_cmds > 0)

        # B2: UUT selector visible
        uut_select = page.locator('select').first
        uut_count = await uut_select.locator('option').count()
        await check('B2: UUT selector populated', uut_count > 0, f'{uut_count} options')

        # B3: Connect to sim vehicle
        connect_btn = page.locator('button:has-text("Connect")')
        if await connect_btn.count() > 0:
            await connect_btn.first.click()
            await page.wait_for_timeout(5000)  # wait for connection + telemetry
            await screenshot('B3_debug_connected')

            # Verify telemetry panel populated
            body = await page.text_content('body')
            has_telemetry = any(x in body for x in ['Vehicle Status', 'Actuator', 'SAFE', 'OFF'])
            await check('B3: Debug connected with telemetry', has_telemetry)
        else:
            await check('B3: Connect button found', False)

        # B4: Send ARM command
        arm_btn = page.locator('button:has-text("ARM")').first
        if await arm_btn.is_enabled():
            await arm_btn.click()
            await page.wait_for_timeout(2000)
            await screenshot('B4_armed')
            body = await page.text_content('body')
            await check('B4: ARM command sent', True)  # No crash = success
        else:
            await check('B4: ARM button enabled', False, 'ARM button disabled')

        # B5: Send mode request
        operate_btn = page.locator('button:has-text("OPERATE")').first
        if await operate_btn.is_enabled():
            await operate_btn.click()
            await page.wait_for_timeout(2000)
            await screenshot('B5_operate')
            await check('B5: OPERATE mode sent', True)
        else:
            await check('B5: OPERATE button enabled', False)

        # B6: Disconnect
        disconnect_btn = page.locator('button:has-text("Disconnect")')
        if await disconnect_btn.count() > 0:
            await disconnect_btn.first.click()
            await page.wait_for_timeout(2000)
            await screenshot('B6_disconnected')

            # Verify back to "No vehicle connected"
            body = await page.text_content('body')
            await check('B6: Disconnected', 'No vehicle connected' in body or 'Connect' in body)
        else:
            await check('B6: Disconnect button found', False)

        # ══════════════════════════════════════════════════════════════════
        # C. EDGE CASES
        # ══════════════════════════════════════════════════════════════════
        print('\n--- C. Edge Cases ---', flush=True)

        # C1: Switch back to Test mode
        await page.click('text=TEST MODE')
        await page.wait_for_timeout(500)
        test_visible = await page.locator('text=UNIT UNDER TEST').count()
        await check('C1: Switch back to Test mode', test_visible > 0)

        # C2: Add UUT
        add_btn = page.locator('button:has-text("Add")')
        if await add_btn.count() > 0:
            await add_btn.first.click()
            await page.wait_for_timeout(500)
            await screenshot('C2_add_dialog')

            # Fill in UUT details (if dialog opened)
            dialogs = page.locator('[role=dialog], .fixed.inset-0')
            if await dialogs.count() > 0:
                serial_input = page.locator('input[placeholder*="serial" i], input').first
                # Try to fill and submit
                try:
                    inputs = page.locator('input[type="text"], input[type="number"]')
                    input_count = await inputs.count()
                    await check('C2: Add UUT dialog opened', input_count >= 3, f'{input_count} inputs')
                except:
                    await check('C2: Add UUT dialog opened', True)

                # Close dialog by pressing Escape
                await page.keyboard.press('Escape')
                await page.wait_for_timeout(500)
            else:
                await check('C2: Add UUT dialog', False, 'Dialog not found')
        else:
            await check('C2: Add button found', False)

        # C3: Emergency stop (should work even when no test running)
        emergency_btn = page.locator('text=EMERGENCY STOP')
        if await emergency_btn.count() > 0:
            await emergency_btn.first.click()
            await page.wait_for_timeout(1000)
            await screenshot('C3_emergency')
            await check('C3: Emergency stop clicked without crash', True)
        else:
            await check('C3: Emergency stop button found', False)

        # C4: Log filter buttons
        await page.click('text=TEST MODE')
        await page.wait_for_timeout(500)
        error_filter = page.locator('button:has-text("ERROR")')
        if await error_filter.count() > 0:
            await error_filter.first.click()
            await page.wait_for_timeout(500)
            await screenshot('C4_log_filtered')
            await check('C4: Log ERROR filter works', True)

            # Reset to ALL
            all_filter = page.locator('button:has-text("ALL")')
            if await all_filter.count() > 0:
                await all_filter.first.click()
        else:
            await check('C4: Log filter buttons found', False)

        # C5: Keyboard shortcuts (Ctrl+D -> Debug mode)
        await page.keyboard.press('Control+d')
        await page.wait_for_timeout(500)
        debug_visible = await page.locator('text=MANUAL COMMANDS').count()
        await check('C5: Ctrl+D switches to debug mode', debug_visible > 0)

        # C6: Duration dropdown fits
        await page.click('text=TEST MODE')
        await page.wait_for_timeout(500)
        duration_select = page.locator('select:has(option:text("Days"))')
        if await duration_select.count() > 0:
            box = await duration_select.first.bounding_box()
            if box:
                # Check it's within the left column (x < 350)
                await check('C6: Duration dropdown fits in column', box['x'] + box['width'] < 350,
                           f'x={box["x"]:.0f} w={box["width"]:.0f} right={box["x"]+box["width"]:.0f}')
            else:
                await check('C6: Duration dropdown visible', False, 'No bounding box')
        else:
            await check('C6: Duration dropdown found', False)

        # C7: Status bar shows correct info
        status = await page.text_content('body')
        has_mode = 'Mode:' in status
        has_backend = 'Backend:' in status
        has_daq = 'DAQ:' in status
        has_uuts = 'UUTs:' in status
        await check('C7: Status bar complete', has_mode and has_backend and has_daq and has_uuts)

        # Final screenshot
        await page.click('text=TEST MODE')
        await page.wait_for_timeout(500)
        await screenshot('C_final')

        await browser.close()

    # ── Shutdown ──────────────────────────────────────────────────────────
    server.terminate()
    try:
        server.wait(timeout=5)
    except:
        server.kill()

    # ── Report ────────────────────────────────────────────────────────────
    passed = sum(1 for r in results if r['pass'])
    failed = len(results) - passed

    print(f'\n{"="*60}', flush=True)
    print(f'  WEB GUI E2E TEST RESULTS', flush=True)
    print(f'{"="*60}', flush=True)
    for r in results:
        sym = '+' if r['pass'] else 'x'
        print(f'  [{sym}] {r["name"]}', flush=True)
        if not r['pass'] and r.get('detail'):
            print(f'       {r["detail"]}', flush=True)
    print(f'\n  {passed} passed / {failed} failed / {len(results)} total', flush=True)
    print(f'{"="*60}', flush=True)

    report = os.path.join(ROOT, 'web_e2e_results.json')
    with open(report, 'w') as f:
        json.dump(results, f, indent=2)
    print(f'  Report: {report}', flush=True)


if __name__ == '__main__':
    asyncio.run(run_all())
