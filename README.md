# Roadrunner Flight Mode IBIT Test System

Automated reliability test system for the Roadrunner UAV flight controller
actuation subsystem. Runs the vehicle's built-in IBIT (Integrated Built-In
Test) and Flight Profile Playback tests over MAVLink (Pandion dialect)
across up to 6 UUTs simultaneously.

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+ (for the frontend build; one-time)
- NI-DAQmx drivers (optional — for hardware relay control)

### Install

```bash
pip install -r requirements.txt
cd web && npm install && npm run build && cd ..
```

### Run (Production — with hardware)

```bash
start.bat
```

Launches `ws_server.py` and opens the web GUI at
<http://localhost:18890>. Closes the server when the window is closed
(or Ctrl+C).

### Run (Simulation — no hardware needed)

```bash
start.bat --sitl
```

This launches `ws_server.py --sitl`, which spins up two simulated Pandion
vehicles (SIM-001 pass, SIM-002 fail) and opens the web GUI. Useful for
development, testing, and demo.

On Linux/macOS (WSL):

```bash
python ws_server.py --sitl
```

### Run Integration Tests

```bash
# Full web GUI V&V (headless, ~2 min)
python tests/test_web_gui_e2e.py

# Operator-perspective walkthrough (~3 min)
python tests/new_user_walkthrough.py

# SITL integration
python tests/test_sitl.py

# Full headed browser V&V (Windows, ~5 min)
tests\vv\run_vv.bat
```

## What It Does

1. **Powers each vehicle on** via NI-DAQmx relay
2. **Connects over UDP MAVLink** (Pandion dialect 102, port 13002)
3. **ARMs the vehicle**, clearing safety monitors iteratively
4. **Transitions through the firmware state machine**:
   OFF → OPERATE → PLAYBACK → IBIT
5. **Runs the IBIT sequence** — the vehicle commands its own servos through
   triangle waves (elevons/rudders) and circular patterns (TVC)
6. **Reads the mistracking bitmask** at completion to determine PASS/FAIL
   per surface (500 cdeg threshold, firmware-enforced)
7. **Restores vehicle state**, disarms, powers off
8. **Repeats** across all UUTs in round-robin for the configured duration
9. **Logs everything** to daily-rotated CSV files and batch JSON reports

## Project Structure

```
start.bat                    One-click Windows launcher
ws_server.py                 Web GUI backend — WebSocket + HTTP server
version.py                   Version constant
config.yaml                  Reference config (runtime uses app_settings.json)
requirements.txt             Pinned Python dependencies

web/                         React + TypeScript frontend
  src/
    App.tsx                  Top-level app component
    hooks/use-websocket.ts   WebSocket hook + reducer
    lib/ws-client.ts         Auto-reconnect WebSocket client
    lib/types.ts             Event type definitions
    components/              VehicleStatus, UUTTable, IBITDisplay,
                             ActuatorFeedback, ControlBar, etc.
    pages/                   TestMode, DebugMode
  dist/                      Built bundle (served by ws_server.py)

vehicle/                     Vehicle communication
  constants.py               Single source of truth for all enums
  connection.py              MAVLink UDP connection + UUT model
                             (RR_SITL_MODE env var enables loopback)
  preparation.py             ARM/DISARM, mode transitions, monitor mgmt
  dialects/                  Pandion MAVLink XML + generated Python

testing/                     Test execution
  base_executor.py           Shared mixin (heartbeat, connection, relay)
  ibit_executor.py           IBIT test executor
  playback_executor.py       Flight profile playback executor
  callbacks.py               Plain-Python callback protocols
  recovery.py                Auto-recovery manager (3-strike logic)
  tracker.py                 IBIT phase tracker + test statistics
  logger.py                  Telemetry CSV logger (daily rotation)

hardware/                    Hardware abstraction
  daq.py                     NI-DAQmx relay controller

sim/                         Software-In-The-Loop simulator
  vehicle.py                 Vehicle orchestrator (FSM, IBIT lifecycle)
  telemetry.py               12 MAVLink TX message types
  mock_daq.py                Drop-in DAQ replacement
  config/defaults.py         Firmware-accurate constants
  config/scenarios.py        10 pre-built fault profiles
  models/                    servo, battery, monitors, sensors

tests/                       Active test suites
  test_web_gui_e2e.py        Headless web GUI V&V (27/27)
  new_user_walkthrough.py    Operator-perspective walkthrough
  test_sitl.py               SITL integration tests
  test_permutations.py       Combinatorial scenario testing
  web_e2e_test.py            Web-specific E2E
  vv/                        Headed Playwright V&V (run_vv.bat)

archive/                     Historical/reference code
  desktop_gui/               PyQt5 desktop GUI (replaced by web GUI)
```

## Test Modes

| Mode | Description |
|------|-------------|
| **IBIT** | Vehicle runs its own built-in self-test. Software triggers it and reads the mistracking result. Pass/fail determined by firmware (500 cdeg threshold). |
| **Flight Profile Playback** | Software streams recorded CSV commands at 100 Hz. Pass/fail determined by accumulated mistracking flags across all frames. |

## Architecture

- See [ARCHITECTURE.md](ARCHITECTURE.md) for system architecture, threading
  model, and design decisions
- See [V_AND_V_REPORT.md](V_AND_V_REPORT.md) for the latest verification
  status (test results + fixes)
- See [SESSION_KNOWLEDGE.md](SESSION_KNOWLEDGE.md) for full project context,
  bug-fix history, and firmware compatibility notes
- See [archive/desktop_gui/README.md](archive/desktop_gui/README.md) for
  the archived PyQt5 GUI

## Repository

- **GHE**: https://ghe.anduril.dev/jbauzon/roadrunner-flightmode-reliability
- **Jira**: https://jira.anduril.dev/browse/AIT-2081
