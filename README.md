# Roadrunner Flight Mode IBIT Test System

Automated reliability test system for the Roadrunner UAV flight controller actuation subsystem. Runs the vehicle's built-in IBIT (Integrated Built-In Test) and Flight Profile Playback tests over MAVLink (Pandion dialect) across up to 6 UUTs simultaneously.

## Quick Start

### Prerequisites

- Python 3.11+
- NI-DAQmx drivers (optional — for hardware relay control)

### Install

```bash
pip install -r requirements.txt
```

### Run (Production — with hardware)

```bash
python main.py
```

### Run (Simulation — no hardware needed)

```bash
python run_sim.py
```

This launches the SITL simulator (2 simulated vehicles) and the GUI with a mock DAQ controller. Useful for development, testing, and demo.

### Run Integration Tests

```bash
python tests/test_sitl.py
```

68 tests covering the full SITL: heartbeat, telemetry streams, ARM/DISARM, mode transitions, IBIT execution with pass/fail, monitor management, battery/engine/INS/GNSS telemetry.

## What It Does

1. **Powers each vehicle on** via NI-DAQmx relay
2. **Connects over UDP MAVLink** (Pandion dialect)
3. **ARMs the vehicle**, clearing safety monitors iteratively
4. **Transitions through the firmware state machine**: OFF → OPERATE → PLAYBACK → IBIT
5. **Runs the IBIT sequence** — the vehicle commands its own servos through triangle waves (elevons/rudders) and circular patterns (TVC)
6. **Reads the mistracking bitmask** at completion to determine PASS/FAIL per surface
7. **Restores vehicle state**, disarms, powers off
8. **Repeats** across all UUTs in round-robin for the configured duration
9. **Logs everything** to daily-rotated CSV files and batch JSON reports

## Project Structure

```
main.py                      Application entry point (PyQt5 GUI)
run_sim.py                   Simulation launcher (patches + launches)
version.py                   Single source of truth for version string
config.yaml                  Reference config (runtime uses app_settings.json)
requirements.txt             Pinned dependencies
launch_sim.bat               Windows batch launcher

ui/                          GUI layer
  main_window.py             Operator console — 3-column layout
  widgets.py                 Reusable Qt widgets (status panel, IBIT display, etc.)
  theme.py                   Dark theme stylesheet
  command_server.py          TCP server for remote GUI control

vehicle/                     Vehicle communication
  constants.py               Single source of truth for all enums and constants
  connection.py              MAVLink UDP connection and UUT model
  preparation.py             ARM/DISARM, mode transitions, monitor management
  dialects/                  Pandion MAVLink XML + generated Python

testing/                     Test execution
  executor.py                IBIT and Playback test executors
  logger.py                  Telemetry CSV logger with daily rotation

hardware/                    Hardware abstraction
  daq.py                     NI-DAQmx relay controller

sim/                         Software-In-The-Loop simulator
  vehicle.py                 Vehicle orchestrator (state machine, IBIT lifecycle)
  telemetry.py               12 MAVLink TX message types
  fleet.py                   Cross-vehicle noise injection
  mock_daq.py                Drop-in DAQ replacement for simulation
  bridge.py                  MAVLink bridge utilities
  config/defaults.py         Sim constants (backed by production enums)
  config/scenarios.py        10 pre-built fault profiles
  models/servo.py            Servo dynamics with thermal protection
  models/battery.py          7S LiPo BMS model
  models/monitors.py         Condition-based monitor evaluation
  models/sensors.py          INS/GNSS boot progression

tests/                       Test suites
  test_sitl.py               68-test SITL integration suite
  test_permutations.py       Combinatorial scenario testing
  test_gui_live.py           Live GUI E2E test with screenshot capture

tools/                       Utilities
  gui_test.py                Headless GUI screenshot capture
  click_start.py             TCP remote control client
  analyze_screenshots.py     Screenshot metadata tool
```

## Test Modes

| Mode | Description |
|------|-------------|
| **IBIT** | Vehicle runs its own built-in self-test. Software triggers it and reads the mistracking result. Pass/fail determined by firmware (500 cdeg threshold). |
| **Flight Profile Playback** | Software streams recorded CSV commands at 100 Hz. Pass/fail determined by accumulated mistracking flags across all frames. |

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for detailed system architecture, threading model, data flow, and design decisions.

## Repository

- **GHE**: https://ghe.anduril.dev/jbauzon/roadrunner-flightmode-reliability
- **Jira**: https://jira.anduril.dev/browse/AIT-2081
