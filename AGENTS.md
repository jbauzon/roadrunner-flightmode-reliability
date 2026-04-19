# Roadrunner Flight IBIT Test - Agent Context

## Overview
Automated reliability test system for the Roadrunner UAV flight controller.
Runs the vehicle's built-in IBIT and Flight Profile Playback across up to
6 UUTs, designed for unattended multi-day operation.

## Tech stack
- Python 3.11+ (see `pyproject.toml`)
- pymavlink (Pandion dialect 102)
- websockets (WebSocket backend for the React web GUI)
- React 19 + TypeScript + Vite (web frontend)
- NI-DAQmx (optional, Windows only, for real-hardware relay control)

## Layout
- `ws_server.py` — thin shim that runs `rr_test.server.main()`
- `rr_test/vehicle/` — MAVLink connection, constants, preparation
- `rr_test/execution/` — IBIT + playback executors, callbacks, recovery
- `rr_test/sim/` — SITL Pandion simulator
- `rr_test/hardware/` — NI-DAQmx relay controller
- `rr_test/server/server.py` — Web GUI backend (WebSocket + HTTP)
- `web/` — React frontend
- `tests/` — pytest suite + operator walkthroughs
- `archive/desktop_gui/` — legacy PyQt5 GUI (deprecated, kept for reference)

## Key behaviors
- **SITL mode:** `RR_SITL_MODE=1` env var must be set before
  `rr_test.execution` imports.  The `--sitl` flag on `ws_server.py`
  sets it automatically.
- **Port 13002** — production MAVLink UDP (Pandion dialect).
- **Port 18889 / 18890** — WebSocket / HTTP for the web GUI.
- **`app_settings.json`** — runtime state, gitignored.

## Agent conventions (for AI coding tools working on this repo)
- Load the `roadrunner-vehicle` skill when working on Roadrunner MAVLink or
  the actuation state machine
- Load the `pyqt-hil-patterns` skill only when touching `archive/desktop_gui/`
