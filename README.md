# Roadrunner Flight Mode IBIT Test System

Automated reliability test tool for the Roadrunner UAV flight controller
actuation subsystem.  Runs IBIT (Integrated Built-In Test) and Flight
Profile Playback over MAVLink (Pandion dialect 102), with a web-based
operator UI.  Supports up to 6 UUTs simultaneously.

## Install (Windows)

Prerequisites:

- **Python 3.11+** — <https://www.python.org/downloads/> (check "Add Python to PATH")
- **Node.js 20 LTS** — <https://nodejs.org/>
- **NI-DAQmx driver** — <https://www.ni.com/en-us/support/downloads/drivers/download.ni-daq-mx.html>

Then:

1. Copy or clone this folder to the test bench computer
2. Double-click **`start.bat`**

That's it.  On first launch it auto-installs Python dependencies and
builds the web frontend (~2 minutes, needs internet).  A browser window
opens to <http://localhost:18890>.

Subsequent launches are instant.

## Usage

1. **Add UUTs** — enter serial number, IP address, port, and relay line for each vehicle
2. **Select test mode** — IBIT or Flight Profile Playback
3. **Set duration** — hours/days for the batch run
4. **Click Start** — the system ARMs each vehicle, runs the test, evaluates PASS/FAIL, and repeats round-robin until duration expires
5. **Monitor** — watch live telemetry, IBIT phase progression, and iteration counts in the GUI

For Playback mode, click the folder icon to upload a flight profile CSV
before starting.

## Debug Mode

Switch to the Debug tab to manually verify each vehicle before starting
a batch:

- Connect to a vehicle and watch live telemetry
- Send ARM / DISARM commands
- Request actuation modes (OPERATE, PLAYBACK, IBIT)
- Override monitors, set parameters
- Verify the vehicle responds correctly before committing to an overnight run

## What it does

1. Powers each vehicle on via NI-DAQmx relay
2. Connects over UDP MAVLink (Pandion dialect 102, port 13002)
3. ARMs the vehicle, clearing safety monitors iteratively
4. Transitions: `OFF → OPERATE → PLAYBACK → IBIT`
5. Runs IBIT (firmware-internal actuator sweeps) or streams Playback commands at 100 Hz
6. Reads the mistracking bitmask (500 cdeg threshold) to determine PASS/FAIL
7. Restores vehicle state, DISARMs, powers off
8. Repeats round-robin across all UUTs for the configured duration
9. Logs to daily-rotated CSVs

## Test modes

| Mode | How it works |
|------|-------------|
| **IBIT** | Vehicle runs its own built-in self-test. Software triggers it and reads the result. PASS = mistracking flags 0x00. |
| **Flight Profile Playback** | Software streams a recorded CSV at 100 Hz. CSVs recorded at other rates (e.g. 500 Hz) are auto-resampled. PASS = all surface deltas ≤ 500 cdeg. |

## Project layout

```
start.bat           One-click launcher (auto-installs on first run)
ws_server.py        Backend entry point
pyproject.toml      Python package metadata

rr_test/            Python package
  vehicle/          MAVLink connection, constants, preparation
  execution/        IBIT + playback executors, callbacks, recovery
  sim/              SITL simulator (for development/testing without hardware)
  hardware/         NI-DAQmx relay controller
  server/           Web GUI backend (app_state, broadcaster, handlers)

web/                React + TypeScript frontend
tests/              Test suite + operator walkthroughs
scripts/            Install helpers
profiles/           Reference flight profile CSVs
docs/               Architecture, V&V report, config reference
archive/            Deprecated PyQt5 desktop GUI (reference only)
```

## For developers

See [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup and test commands.

To run without hardware (simulator mode):

```
start.bat --sitl
```

## Docs

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — system design
- [docs/V_AND_V_REPORT.md](docs/V_AND_V_REPORT.md) — verification status
- [CHANGELOG.md](CHANGELOG.md) — release history

## License

Apache 2.0 — see [LICENSE](LICENSE).
