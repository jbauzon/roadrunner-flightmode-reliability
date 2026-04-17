# Roadrunner Flight Mode IBIT — Complete Session Knowledge Base
# Last updated: 2026-04-16
# Session: Full development from scratch to production-ready

## CRITICAL: Web GUI Issues Found (Not Yet Fixed)

The web GUI (`ws_server.py` + `web/`) has 7 UX bugs discovered in the final audit:

1. **Vehicle Status shows "OFFLINE" during active test** — `connection.health` event not mapped to Link indicator
2. **Vehicle Status never changes from SAFE/OFF** — `telemetry.vehicle_status` events not flowing to right panel
3. **Test Status shows "IDLE" during entire test** — `ibit.state` events not received/displayed, phase stepper never lights up
4. **Actuator Feedback shows "---" during test** — `telemetry.actuator` events not flowing
5. **Elapsed/Remaining shows 00:00** — batch timer not updating, `batch.status` ticker not working
6. **No getting-started hint in web log** — empty log with no guidance
7. **Iterations stays at 0 after test** — UUT table doesn't update iteration count

**Root cause:** `ws_server.py` `wire_callbacks()` wires executor callbacks to `Broadcaster`, but the vehicle status, actuator feedback, IBIT state, and relay state callbacks aren't broadcasting with the correct event types that the frontend `use-websocket.ts` reducer expects. The `_run_batch` method creates executors and wires callbacks, but the telemetry worker in the executor reads from the dispatch queue and emits callbacks — these callbacks need to map to the WebSocket broadcast event types.

**Fix approach:** In `ws_server.py`, the `wire_callbacks()` function needs to add:
- `cb.on_actuator_feedback` → broadcast `telemetry.actuator`
- `cb.on_armed_state` → broadcast `telemetry.vehicle_status` with mode/regime/armed
- `cb.on_mode` → broadcast `telemetry.vehicle_status`
- `cb.on_connection_health` → broadcast `connection.health`
- `cb.on_ibit_state` → broadcast `ibit.state`
- `cb.on_mistracking_update` → broadcast `ibit.mistracking`
- `cb.on_relay_state` → broadcast `daq.relay`
- `cb.on_iteration` → update UUT iterations and broadcast `uut.update`
- `cb.on_test_duration` → broadcast `test.duration`

The `_batch_ticker` coroutine also needs to broadcast `batch.status` every second with correct elapsed/remaining times.

---

## Project Overview
Production-grade automated reliability test system for the Roadrunner UAV flight controller actuation subsystem. Runs IBIT and Flight Profile Playback tests over MAVLink (Pandion dialect) across up to 6 UUTs simultaneously.

**Repository:** https://ghe.anduril.dev/jbauzon/roadrunner-flightmode-reliability (public to Anduril)
**Jira:** https://jira.anduril.dev/browse/AIT-2081
**Owner:** jbauzon@anduril.com

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

## Jira: AIT-2081 parent, AIT-2124-2130 sub-tasks (2130=bench bring-up is To Do)

## What's Left
1. Fix 7 web GUI UX bugs (see top of file)
2. Hardware bench bring-up
3. Playback CSV compatibility with QGC exports
4. Engine management in playback mode
