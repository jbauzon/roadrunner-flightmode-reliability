# Roadrunner Flight Mode IBIT Test System — Session Knowledge Base

## Project Overview
Production-grade automated reliability test system for the Roadrunner UAV flight controller actuation subsystem. Runs IBIT (Integrated Built-In Test) and Flight Profile Playback tests over MAVLink (Pandion dialect) across up to 6 UUTs simultaneously.

**Repository:** https://ghe.anduril.dev/jbauzon/roadrunner-flightmode-reliability
**Jira:** https://jira.anduril.dev/browse/AIT-2081
**Owner:** jbauzon@anduril.com

---

## Architecture

### Two GUIs
1. **PyQt5 GUI** (`main.py`, `run_sim.py`) — original desktop app, fully functional
2. **Web GUI** (`ws_server.py` + `web/`) — React/TypeScript frontend over WebSocket, newer

### Backend Layers
```
ui/                    PyQt5 GUI (widgets/ sub-package, qt_adapter.py, command_server.py)
web/                   React 19 + Vite + TailwindCSS frontend
ws_server.py           asyncio WebSocket backend (port 18889) + HTTP server (port 18890)
vehicle/               MAVLink connection, ARM/preparation, centralized constants
  constants.py         Single source of truth for ALL enums, modes, thresholds
  connection.py        UUT model + connect_to_vehicle()
  preparation.py       ARM→OPERATE→PLAYBACK→IBIT state machine
testing/               Test execution (split into 6 modules)
  ibit_executor.py     IBIT test with mistracking detection
  playback_executor.py Flight profile playback at 100Hz
  base_executor.py     _ExecutorMixin (heartbeat, relay, dispatch worker)
  tracker.py           IBITPhaseTracker, TestStatistics
  recovery.py          RecoveryManager (soft/hard/fatal classification)
  watchdog.py          BatchWatchdog (relay safety, disk, memory, hourly summary)
  error_logger.py      Persistent JSONL error log
  callbacks.py         ExecutorCallbacks, PreparationCallbacks (no Qt dependency)
  debug_connection.py  Lightweight MAVLink connection for debug mode
hardware/              NI-DAQmx relay controller
sim/                   SITL simulator
  vehicle.py           Full Pandion state machine + IBIT lifecycle
  telemetry.py         12 MAVLink message types
  models/              servo dynamics, battery, monitors, sensors
  config/              defaults (backed by production enums), scenarios, composition
  clock.py, recorder.py, fuzzer.py
```

### Key Design Decisions
- **Production code never modified for simulation** — `run_sim.py` patches `connect_to_vehicle` at runtime
- **PyQt5 decoupled from non-UI layers** — executor/preparation/logger use plain callbacks, Qt adapter bridges to signals
- **vehicle/constants.py is single source of truth** — all enums, mode names, timeouts, monitor IDs
- **Sim enums backed by production enums** — `sim/config/defaults.py` imports from `vehicle/constants.py`
- **Relays are TEST LOAD relays, NOT main power** — vehicle stays powered regardless of relay state

---

## Critical Firmware Compatibility (Verified Against Source)

### ARM Command
- `MAV_CMD_COMPONENT_ARM_DISARM` (command 400), param1=1 (ARM), param2=21196 (force ARM bypass monitors)
- Returns `COMMAND_ACK` result=0 (ACCEPTED) or result=1 (TEMPORARILY_REJECTED)

### Mode Transitions
- Required sequence: OFF → OPERATE → PLAYBACK → IBIT
- Direct OPERATE → IBIT is NOT permitted
- Mode request: `pandion_rr_actuation_request_mode_send(requested_mode=N)`
- Silently ignored when not armed

### Monitor Override Semantics
- cmd=0 (CANCEL): Remove override, return to normal monitoring
- cmd=1 (SUPPRESS): Override to healthy (use to clear SET monitors)
- cmd=2 (FORCE_FAULT): Override to faulted (makes things worse, not better)

### IBIT Mistracking Detection
- Threshold: 500 cdeg (5°) for all surfaces
- TVC: 5 consecutive cycles at 100Hz (50ms)
- Elevons/rudders: instantaneous
- **Firmware zeros `actuation_ibit_mon_status` on OPERATE transition** — must accumulate flags via |= during IBIT

### Phase Durations (firmware-accurate)
- SETTLE: 500ms, ELEVON: 5000ms, RUDDERS: 10000ms, TVC: 5000ms
- No COMPLETE phase — transitions immediately to OPERATE

### Default Port
- Vehicle MAVLink: port 13002 (QGC channel)
- NOT 9985 (that was wrong)

### Monitor IDs (from cm_config.xml)
- Monitor 6: Actuator Controller Temp Warning (≥95°C PCB)
- Monitor 7: Actuator Controller Temp Critical (≥105°C PCB)
- Monitor 9: Actuator Controller Thermal Limit Active
- Monitor 52: Elevon Controller Internal Limit Active (NOT thermal)
- Monitor 55: Servo IBIT Mistracking

### Parameter Names
- `USE_NEST` — nest connection control
- `CLASSIC_MODE_EN` — requires power cycle to activate (stored vs active params)
- Response: `PANDION_RR_PARAM_VALUE` (not standard `PARAM_VALUE`)

---

## Bugs Found and Fixed

### Critical Firmware Compat Bugs (would have caused wrong results on real hardware)
1. **IBIT always reported PASS** — read mistracking from OPERATE message (always 0x00). Fixed: accumulate via |= during IBIT
2. **Monitor clearing inverted** — sent FORCE_FAULT(2) instead of SUPPRESS(1). Fixed.
3. **Wrong default port** — 9985 → 13002
4. **Wrong param response type** — tried `PARAM_VALUE`, firmware sends `PANDION_RR_PARAM_VALUE`. Fixed: try both.

### 31 Edge Cases Fixed
- Dispatch worker dying silently → emergency relay disable
- Soft retry infinite loop → 6-failure cap
- `time.time()` vs `time.monotonic()` → NTP/hibernation safe
- Stale message queues blocking mode transitions → queue flush before mode requests
- All-UUTs-failed infinite scheduler loop → early batch completion
- None MAVLink fields → `safe_int_field()` helper
- Window close with relay ON → `set_all_low()` before close dialog
- And 24 more documented in the codebase

---

## SITL Simulator

### Firmware-Accurate Features
- Triangle wave IBIT profiles for elevons/rudders
- Radial sweep for TVC
- Real mistracking detection (|cmd-fb| > 500 cdeg)
- Monitor continuous evaluation (auto-clear when condition becomes false)
- Non-linear LiPo discharge curve
- Engine spool-up sequence (3s ramp)
- IBIT direct servo mode (40000 cdeg/s physical speed, no manual rate limit)
- POS_CHECK state for TAU Mk2 elevons
- X-tail rudder skip
- Deterministic clock, telemetry recording, protocol fuzzer

### What the Sim Doesn't Model
- Actual aerodynamic loads on servos
- Electrical bus transients during relay switching
- Multi-board communication latency
- Watchdog/reset behavior
- Actual servo motor inertia

---

## Web GUI (ws_server.py + web/)

### Architecture
- `ws_server.py`: asyncio WebSocket server (port 18889) + HTTP static file server (port 18890)
- `web/`: React 19 + TypeScript + Vite + TailwindCSS
- Communication: JSON messages over WebSocket (defined in `web/src/lib/types.ts`)
- Launch: `start.bat` (opens browser automatically)

### UUT Status Normalization
Python → TypeScript mapping:
- "Ready" → "READY"
- "Testing" → "TESTING"
- "Complete" → "PASSED"
- "Failed (3x)" → "FAILED_PERMANENT"
- "Retry" → "RETRY"
- "Stopped" → "SKIPPED"

### Debug Mode
- Connect/Disconnect to UUTs without running a test
- Send mode requests, ARM/DISARM, parameter sets, monitor overrides
- Live telemetry panel (vehicle status, actuator feedback, battery, engine)
- Message stream
- SITL launch hidden in Advanced settings

### Known Issues
- Electron packaging doesn't work (path resolution in packaged app). Use `start.bat` instead.
- `QTimer.singleShot(0, ...)` from non-Qt threads doesn't work on Windows — must use `pyqtSignal`
- `time.sleep()` on Qt main thread freezes UI — all blocking work must be in background threads

---

## Test Coverage

| Suite | Count | What |
|-------|-------|------|
| SITL integration | 100 | MAVLink-level: heartbeat, telemetry, ARM, IBIT, monitors, battery, engine |
| Functional | 17 | Module imports, GUI launch, IBIT E2E PASS/FAIL, emergency stop, command server |
| Edge cases | 22 | Configuration validation, safety guards, failure modes, state machine, relay |
| Debug mode | 22 | Connection lifecycle, mode requests, ARM/DISARM, params, monitors, telemetry |
| Permutations | 29 | IBIT/playback × UUT configs × stop methods |
| 24h soak | 1 | Memory, threads, log rotation, relay safety over simulated 24 hours |

---

## Windows-Specific Issues
- WinError 10054: ICMP port-unreachable poisons UDP sockets → handled with try/except in dispatch worker
- WinError 10022: `socket.recvfrom` on `udpout` → wrapped
- Unicode cp1252 crash → `sys.stdout.reconfigure(encoding='utf-8')`
- Qt offscreen mode: signals don't dispatch reliably → use real display for GUI tests
- `QTimer.singleShot` from background threads: doesn't work → use `pyqtSignal`
- `time.sleep` on main thread: freezes GUI → use background threads with signal handoff

---

## Jira Tickets
- **AIT-2081**: Parent story — RR BLK 1 Flight Mode Reliability Test Software
- **AIT-2124**: Research Pandion MAVLink protocol requirements (Done)
- **AIT-2125**: Design and build IBIT test execution engine (Done)
- **AIT-2126**: Design and build operator GUI (Done)
- **AIT-2127**: Build SITL simulator for software validation (Done)
- **AIT-2128**: Verify test software against Pandion firmware (Done)
- **AIT-2129**: Harden for continuous unattended operation (Done)
- **AIT-2130**: Hardware bench bring-up (To Do)

---

## How to Run

### Web GUI (production)
```
cd "C:\Anduril\RoadRunner Flight Mode IBIT"
start.bat
```
Opens browser at http://localhost:18890

### PyQt5 GUI (production)
```
python main.py
```

### PyQt5 GUI with SITL
```
python run_sim.py
```

### SITL Tests
```
python tests/test_sitl.py
```

### Functional Tests
```
python tests/functional_test.py --quick
```

---

## Thermal Chamber Notes
- Servo temperatures monitored by watchdog (warn 70°C, critical 85°C, shutdown 95°C)
- Thermal shutdown monitor = ID 9 (Actuator Controller Thermal Limit Active)
- Temperature field in Advanced Settings for test condition tagging
- IBIT mistracking at extreme temps counts as FATAL (firmware decides pass/fail, not software)

---

## What's Left (Hardware Bench Bring-Up)
1. Wire NI-DAQmx relay box to bench
2. Confirm relay-to-UUT power mapping
3. First live MAVLink connection to real Roadrunner at port 13002
4. Run first live IBIT
5. Verify monitor IDs match specific firmware build (check cm_config.xml)
6. 14-day reliability soak on real hardware
