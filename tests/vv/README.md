# Roadrunner Web GUI — Headed V&V Tool

A **headed** Playwright test that opens a real Chrome window you watch
while it drives the full Roadrunner test software through an IBIT cycle,
verifying all 7 web GUI bug fixes visually in the live UI.

## What It Verifies

| # | Bug Fix | What the Test Watches For |
|---|---------|---------------------------|
| 1 | Vehicle Status Link | OFFLINE → CONNECTED during active test |
| 2 | Armed/Mode | SAFE/OFF → ARMED/OPERATE/IBIT |
| 3 | Test Status | IDLE → CONNECTING/BEGIN/SETTLE/ELEVONS/RUDDERS/TVC |
| 4 | Actuator Feedback | "---" → real servo position values |
| 5 | Elapsed/Remaining timers | 00:00 → counting up during test |
| 6 | Log panel | Shows welcome log (not blank) |
| 7 | Iterations column | 0 → 1+ after UUT completes |

## One-Click Run (Windows)

From a Windows command prompt:

```bat
cd "C:\Anduril\RoadRunner Flight Mode IBIT\tests\vv"
run_vv.bat
```

That's it. The script will:

1. Verify Python + Node are installed
2. Install Playwright + Chromium (first run only, ~2 min)
3. Build the React frontend (`npm run build`)
4. Start `ws_server.py --sitl` (auto-launches SIM-001 pass + SIM-002 fail)
5. **Open a Chromium window you watch driving the test** (~60-90s)
6. Stop the backend and show a PASS/FAIL summary

If any step fails the HTML report opens automatically showing
screenshots + traces of what went wrong.

## What You'll See

The browser window opens to `http://localhost:18890` and you'll watch:

1. The app loads with the getting-started log message
2. The SIM-001 and SIM-002 UUTs appear in the table
3. Someone "clicks" the **Start IBIT Test** button
4. **Link** badge transitions from `OFFLINE` → `CONNECTED`
5. **Armed** transitions from `SAFE` → `ARMED`
6. **Mode** cycles through `OFF` → `OPERATE` → `PLAYBACK` → `IBIT`
7. **Test Status** cycles through IBIT substates
8. **Actuator Feedback** table shows live servo positions
9. **Elapsed/Remaining** timers count up/down
10. **Iterations** column increments after each PASS
11. Test ends, batch stops cleanly

The Playwright runner uses `slowMo: 250ms` so every interaction is
visible to the human eye.

## Manual / Advanced Runs

From `tests/vv/`:

```bat
REM Headed run (visible browser window):
npm run test:headed

REM Playwright Inspector UI (interactive step-through):
npm run test:ui

REM Debug mode (DevTools open in browser):
npm run test:debug

REM Headless (CI mode, no browser window):
npm test
```

## Troubleshooting

### "Port 18889/18890 already in use"

A previous backend didn't shut down cleanly. Kill it:

```bat
netstat -ano | findstr :18889
taskkill /F /PID <pid>
```

Or just re-run `run_vv.bat` — it auto-cleans leftover processes.

### "Backend did not start within 20s"

Check `vv_backend.log` in the project root for Python errors.
Usually means a missing dependency (`pip install -e .`).

### "Browser window flashes and closes"

First-run browser install may have failed. Run:

```bat
cd tests\vv
npx playwright install chromium --force
```

### Test fails at a specific step

The HTML report (opens automatically on failure) shows:
- Screenshot at failure point
- Full browser video
- Playwright trace (click "View Trace" to step through)

## How It Works Under the Hood

- `playwright.config.ts` — Playwright configuration, headed mode, slowMo
- `web_gui_vv.spec.ts` — The test spec with one `test()` that runs through
  all 7 bug fix assertions as `test.step()` blocks for readable reporting
- `run_vv.bat` — Windows launcher that orchestrates backend + browser

The test connects to `http://localhost:18890` (the backend's static file
server serving the built React app) and uses the same WebSocket endpoint
(`ws://localhost:18889`) the frontend uses — so we're testing the real
deployed bundle, not a dev server.

## Related

- `tests/test_web_gui_e2e.py` — Headless firmware + WS V&V (no browser)
- `docs/SESSION_KNOWLEDGE.md` — Full project context and bug-fix history
