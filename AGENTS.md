# RoadRunner Flight Mode IBIT

## Overview
Automated reliability test system for the Roadrunner UAV flight controller actuation subsystem. Performs IBIT (Integrated Built-In Test) and Flight Profile Playback tests across up to 6 UUTs in round-robin, designed for unattended multi-day operation (default 14 days).

## Tech Stack
- **Language:** Python 3.11+
- **GUI:** PyQt5 ~5.15 (dark-themed operator console, 3-column layout)
- **Protocol:** pymavlink ~2.4 with custom Pandion Roadrunner dialect
- **Hardware:** nidaqmx ~0.6 for relay control (optional)

## Project Structure
- `main.py` -- GUI entry point
- `run_sim.py` -- SITL launcher (vehicles + MockDAQ + GUI)
- `vehicle/` -- MAVLink connection, state machine (ARM/DISARM/mode transitions), Pandion dialect definitions
- `testing/` -- IBIT executor, playback executor, telemetry logger, diagnostics, auto-recovery, batch watchdog
- `hardware/` -- NI-DAQmx relay controller (thread-safe read-modify-write)
- `ui/` -- Main window, 14+ widgets, dark theme, TCP command server, Qt-executor bridge
- `sim/` -- SITL vehicle simulator (servo dynamics, battery model, sensor boot, fault scenarios)
- `tests/` -- See test suite below

## Protocol
- **MAVLink v1** over UDP using **Pandion Vehicle Roadrunner** custom dialect
- Production: `udpin:` on port 13002; Simulation: `udpout:` to localhost
- Key messages: PANDION_STATUS, PANDION_RR_ACTUATION_SYS_STATUS, PANDION_MONITOR_CURRENT_STATUS, PANDION_RR_ENGINE_STATUS, PANDION_RR_BMS_DATA
- State machine: OFF -> OPERATE -> PLAYBACK -> IBIT

## IBIT Test Flow
1. Power on via NI-DAQmx relay
2. Connect over UDP MAVLink
3. ARM vehicle (iteratively clearing safety monitors)
4. Transition: OFF -> OPERATE -> PLAYBACK -> IBIT
5. Run self-test (triangle waves on elevons/rudders, circular on TVC)
6. Read mistracking bitmask for per-surface PASS/FAIL
7. Restore state (DISARM, OFF)
8. Repeat across UUTs for configured duration

## Test Suite
- `tests/test_sitl.py` -- 68 SITL integration tests (heartbeat, telemetry, ARM/DISARM, IBIT lifecycle)
- `tests/test_permutations.py` -- Combinatorial: 6 fault profiles x 4 monitor sets x 3 timing configs
- `tests/test_permutations_gui.py` -- Same permutations through GUI stack
- `tests/test_gui_live.py` -- GUI E2E with SITL, screenshot capture per phase
- `tests/functional_test.py` -- 11 functional areas (imports, SITL, GUI, E2E, batch, e-stop, TCP, 3-strike, CSV, config)
- `tests/soak_test_24h.py` -- 24h endurance at 100x speed (memory, log rotation, timer drift)
- `tests/edge_case_tests.py` -- 7 categories, ~30+ edge cases

**Note:** Tests are standalone scripts with `if __name__` runners, not standard pytest modules. Run them directly with `python tests/<file>.py`.

## Safety Features
- Emergency stop
- Relay safety: all lines LOW on error/shutdown/exception
- 3-strike permanent failure logic
- Auto-recovery from transient faults
- Connection loss monitoring
- Windows sleep prevention for long-duration tests

## Key Patterns
- **Qt-executor bridge** (qt_adapter.py) -- thread-safe signal emission between test executor and GUI
- **Recovery system** -- classifies failures as transient vs. permanent, auto-retries transient
- **Batch watchdog** -- monitors unattended operation, logs anomalies
- **TCP command server** (port 18888) -- JSON-based remote control for CI automation

## Important Notes
- This project is being consolidated into **Nexus** (C:\Anduril\Nexus)
- No mypy or import-linter configured -- less strict than BaDAS or Nexus
- Windows-primary (uses SetThreadExecutionState, Segoe UI, .bat launchers)
- NI-DAQmx drivers only needed for production hardware testing
