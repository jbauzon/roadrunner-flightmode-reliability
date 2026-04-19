# Roadrunner Flight Mode IBIT — Complete Session Knowledge Base
# Last updated: 2026-04-19
# Session: Full development from scratch to production-ready

## ARCHIVED: Desktop PyQt5 GUI (2026-04-19)

The PyQt5 desktop GUI has been moved to `archive/desktop_gui/`. The web GUI
(`ws_server.py` + `web/`) is now the primary and only actively-maintained
operator interface. See `archive/desktop_gui/README.md` for details.

Moved to archive:
- `ui/` (entire widget tree) → `archive/desktop_gui/ui/`
- `main.py` → `archive/desktop_gui/main.py`
- `run_sim.py` → `archive/desktop_gui/run_sim.py`
- `tools/` (all PyQt5-dependent tools) → `archive/desktop_gui/tools/`
- 6 PyQt5-dependent tests → `archive/desktop_gui/tests/`
  (functional_test, test_gui_live, test_permutations_gui, soak_test_24h,
  edge_case_tests, debug_edge_cases)

The domain packages (`vehicle/`, `testing/`, `hardware/`, `sim/`) remain
untouched and are still shared by the web GUI.

## FIXED: Web GUI Issues (7 bugs resolved 2026-04-16)

All 7 web GUI UX bugs have been fixed. Root causes and fixes:

**Root cause analysis:** The `wire_callbacks()` event type strings already matched the
frontend reducer case labels. The actual issues were:

1. **Vehicle Status OFFLINE** — `cb.on_connection_health(True)` was never called at test
   start. The health monitor only broadcasts on state *change* (unhealthy→healthy), but
   never fires the initial healthy state. **Fix:** `_log` callback in `wire_callbacks()`
   detects the "Connected to" log message and broadcasts `connection.health` with
   `healthy=True`. Also, `_run_batch` resets per-UUT state and broadcasts initial states.

2. **Armed/Mode stuck at SAFE/OFF** — Callbacks were wired correctly but per-UUT state
   was never reset between rounds. Frontend carried stale state from the previous UUT.
   **Fix:** `_run_batch` now resets `vehicle_mode`, `vehicle_regime`, `vehicle_armed` and
   broadcasts `telemetry.vehicle_status` with zeroed values before each UUT.

3. **Test Status IDLE** — Same stale-state issue. **Fix:** `_run_batch` broadcasts
   `ibit.state` with `CONNECTING` at the start of each UUT test cycle.

4. **Actuator Feedback ---** — Same stale-state issue. **Fix:** `_run_batch` resets
   `actuator_data` and broadcasts an empty `telemetry.actuator` before each UUT.

5. **Elapsed/Remaining 00:00** — The `_batch_ticker` and `_batch_dict()` were already
   correct. The issue was that `TestStatistics.__dict__` contains `deque` objects which
   are not JSON-serializable, causing `json.dumps` to throw in `_broadcast_async` and
   silently killing broadcasts. **Fix:** `_statistics` callback now converts deques to
   lists and wraps broadcast in try/except.

6. **No getting-started hint** — LogViewer showed bare "No log entries yet". **Fix:**
   LogViewer now shows a 3-step getting-started guide. Also, `_sync_state` handler sends
   a welcome log on client connect so the panel is never empty.

7. **Iterations stays at 0** — `_iteration` callback broadcast `test.iteration` which
   the reducer ignores (`return state // handled via statistics`). **Fix:** `_iteration`
   callback now also broadcasts `uut.update` with the full UUT list so
   `iterations_completed` is visible. `_run_batch` also broadcasts `uut.update` after
   executor completes. Reset `ibit_substate` to IDLE at batch end.

---

## Project Overview
Production-grade automated reliability test system for the Roadrunner UAV flight controller actuation subsystem. Runs IBIT and Flight Profile Playback tests over MAVLink (Pandion dialect) across up to 6 UUTs simultaneously.

**Repository:** <github-url> (public to Anduril)
**Owner:** jbauzon

---

## Two GUIs

### PyQt5 GUI (fully working)
- Entry: `main.py` (production) or `run_sim.py` (with SITL)
- All features working: test mode, debug mode, SITL, telemetry, edge cases

### Web GUI (needs fixes listed above)
- Entry: `start.bat` → opens browser at http://localhost:18890
- Backend: `ws_server.py` (asyncio WebSocket port 18889 + HTTP port 18890)
- Frontend: `web/` (React 19 + TypeScript + Vite + TailwindCSS)
- Build frontend: `cd web && npm install && npm run build`
- SITL: hidden in Advanced settings, or `python ws_server.py --sitl`

---

## Architecture

```
main.py               PyQt5 entry point
run_sim.py             PyQt5 + SITL (patches connect_to_vehicle for loopback)
start.bat              Web GUI launcher (opens browser)
ws_server.py           Web backend (asyncio WebSocket + HTTP static server)
version.py             __version__ = "5.0.0"

vehicle/
  constants.py         SINGLE SOURCE OF TRUTH — all enums, modes, thresholds, monitor IDs
  connection.py        UUT model + connect_to_vehicle() (rejects loopback IPs)
  preparation.py       ARM→OPERATE→PLAYBACK→IBIT state machine (callbacks, no Qt)

testing/
  ibit_executor.py     UUTTestExecutor (threading.Thread, not QThread)
  playback_executor.py PlaybackTestExecutor
  base_executor.py     _ExecutorMixin (dispatch worker, heartbeat, relay, cleanup)
  tracker.py           IBITPhaseTracker, TestStatistics
  callbacks.py         ExecutorCallbacks, PreparationCallbacks (no Qt dependency)
  recovery.py          RecoveryManager (soft/hard/fatal classification)
  watchdog.py          BatchWatchdog (relay safety, disk, memory, hourly summary)
  error_logger.py      Persistent JSONL error log (logs/errors/error_log.jsonl)
  debug_connection.py  Lightweight MAVLink connection for debug mode
  logger.py            Telemetry CSV logger
  helpers.py           _build_actuator_feedback_dict
  diagnostics.py       IBITFailureDiagnostic

hardware/
  daq.py               SimpleDAQController (NI-DAQmx)

sim/
  vehicle.py           Full Pandion state machine + IBIT lifecycle
  telemetry.py         12 MAVLink TX message types
  models/              servo.py, battery.py, monitors.py, sensors.py
  config/              defaults.py (backed by production enums), scenarios.py
  mock_daq.py          MockDAQController (relays are load relays, NOT power)
  clock.py, recorder.py, fuzzer.py, fleet.py, bridge.py

ui/                    PyQt5 GUI
  main_window.py       Operator console
  qt_adapter.py        QtExecutorBridge (ONLY Qt coupling point)
  command_server.py    TCP command server (port 18888)
  widgets/             13 files

web/                   React frontend
  src/pages/           TestMode.tsx, DebugMode.tsx
  src/components/      13 components
  src/hooks/           use-websocket.ts (reducer pattern)
  src/lib/             types.ts, ws-client.ts

tests/                 100 SITL + 17 functional + 22 edge + 22 debug + 29 permutation + soak
tools/                 gui_verify, gui_sitl_verify, operator_test
```

---

## Firmware Compatibility (Verified Against pandion_roadrunner Source)

- ARM: command 400, param1=1, param2=21196 (force)
- Modes: OFF(0) IBIT(1) OPERATE(2) MANUAL(3) PLAYBACK(4) TRIM(5) POS_CHECK(6) TERMINAL(7)
- Sequence: OPERATE → PLAYBACK → IBIT (direct OPERATE→IBIT NOT permitted)
- Monitor override: 0=CANCEL 1=SUPPRESS(clear) 2=FORCE_FAULT(makes worse)
- IBIT mistracking: 500 cdeg, TVC 5-cycle consecutive, elevon/rudder instant
- Phases: SETTLE=500ms ELEVON=5000ms RUDDERS=10000ms TVC=5000ms
- Port: 13002 (NOT 9985)
- Param response: PANDION_RR_PARAM_VALUE
- Firmware zeros actuation_ibit_mon_status on OPERATE transition → accumulate via |=
- Monitor 6=TempWarn 7=TempCrit 9=ThermalLimit 52=ElevonCtrlLimit(NOT thermal) 55=IBITMismatch

---

## Critical Bugs Found and Fixed

1. IBIT always PASS (read from OPERATE msg=0x00) → accumulate via |=
2. Monitor clearing inverted (FORCE_FAULT not SUPPRESS) → cmd=1
3. Wrong port (9985→13002)
4. Wrong param response (PARAM_VALUE→PANDION_RR_PARAM_VALUE)
5. Dispatch worker death → BaseException catch + emergency relay
6. Stale queues blocking mode transitions → flush before request
7. Pre-loop IBIT false positive → require IBIT then OPERATE
8. QTimer.singleShot from non-Qt thread → pyqtSignal
9. time.sleep on main thread → background thread + signal
10. connect_to_vehicle bound at import → module reference

## 31 Edge Cases + Auto-Recovery + Watchdog + Error Logger — all documented in code

## UUT Status Normalization: Ready→READY, Complete→PASSED, Failed(3x)→FAILED_PERMANENT, Retry→RETRY, Stopped→SKIPPED

## Thermal: Monitor 9, warn 70°C, critical 85°C, shutdown 95°C, temperature field in batch report


## What's Left
1. Hardware bench bring-up
2. Playback CSV compatibility with QGC exports
3. Engine management in playback mode
