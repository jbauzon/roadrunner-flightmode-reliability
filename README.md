# Roadrunner Flight Mode IBIT Test System

Automated reliability test tool for the Roadrunner UAV flight controller
actuation subsystem.  Runs the vehicle's built-in IBIT (Integrated
Built-In Test) and Flight Profile Playback over MAVLink (Pandion
dialect 102), with a web-based operator UI.

Supports up to 6 UUTs (units under test) simultaneously via NI-DAQmx
relays, or simulated vehicles via the bundled SITL simulator.

## Install

### Windows (recommended)

1. Install **Python 3.11+** from <https://www.python.org/downloads/>.
   During install, check **"Add Python to PATH"**.
2. Install **Node.js 20 LTS** from <https://nodejs.org/>.
3. (Optional, for real hardware) Install
   [NI-DAQmx](https://www.ni.com/en-us/support/downloads/drivers/download.ni-daq-mx.html).
4. Clone or download this repository to any folder.
5. Double-click `scripts\install.bat` (one-time setup, ~3 minutes).
6. Double-click `start.bat` to run.

On first launch, `start.bat` will auto-run the installer if it hasn't
been set up yet.  Subsequent runs are instant.

### Linux / macOS (SITL only)

```bash
git clone <repo-url>
cd roadrunner-flightmode-reliability
./scripts/install.sh
python ws_server.py --sitl
```

NI-DAQmx hardware support is Windows-only.  SITL mode works anywhere.

## Run

```
start.bat              # real hardware mode (needs NI-DAQmx)
start.bat --sitl       # simulator mode (no hardware needed)
```

The GUI opens at <http://localhost:18890>.

## What it does

1. Powers each vehicle on via NI-DAQmx relay
2. Connects over UDP MAVLink (Pandion dialect 102, port 13002)
3. ARMs the vehicle, clearing safety monitors iteratively
4. Transitions through the firmware state machine:
   `OFF -> OPERATE -> PLAYBACK -> IBIT`
5. Runs the IBIT sequence (firmware-internal triangle/circular actuator sweeps)
6. Reads the mistracking bitmask to determine PASS/FAIL per surface
7. Restores vehicle state, DISARMs, powers off
8. Repeats round-robin across UUTs for the configured duration
9. Logs everything to daily-rotated CSVs and batch JSON reports

Flight Profile Playback mode instead streams a pre-recorded CSV of
servo + engine commands at 100 Hz.  Pass/fail is determined by
accumulated mistracking flags across all frames.

## Project layout

```
start.bat           One-click Windows launcher (auto-installs on first run)
ws_server.py        Backend entry point (web GUI + WebSocket server)
pyproject.toml      Python package metadata (pip install -e .)

rr_test/            Main Python package
  vehicle/          MAVLink connection, constants, preparation (ARM/modes)
  execution/        Test executors + callbacks + recovery
  sim/              SITL Pandion simulator
  hardware/         NI-DAQmx relay controller
  server/           Web GUI backend (WebSocket + HTTP)

web/                React + TypeScript frontend
tests/              pytest test suite + operator walkthroughs
  vv/               Headed Playwright end-to-end V&V
profiles/           Reference flight profile CSVs
docs/               Architecture, V&V report, config reference
archive/            Deprecated PyQt5 desktop GUI (v1-v4, reference only)
scripts/            Install / check helpers
```

## Test modes

| Mode                     | How it works                                                                 |
|--------------------------|------------------------------------------------------------------------------|
| **IBIT**                 | Vehicle runs its own built-in self-test; software reads the mistracking bitmask (500 cdeg threshold, firmware-enforced). |
| **Flight Profile Playback** | Software streams a recorded CSV of servo + engine commands at 100 Hz; mistracking is accumulated across all frames. Upload the CSV via the folder icon in the GUI. |

## Docs

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — system architecture + threading model
- [docs/V_AND_V_REPORT.md](docs/V_AND_V_REPORT.md) — verification & validation status
- [docs/SESSION_KNOWLEDGE.md](docs/SESSION_KNOWLEDGE.md) — project context + firmware notes
- [CONTRIBUTING.md](CONTRIBUTING.md) — dev setup
- [CHANGELOG.md](CHANGELOG.md) — release history

## License

Apache 2.0 — see [LICENSE](LICENSE).
