# Archive — Desktop GUI (PyQt5)

This directory contains the **archived PyQt5 desktop GUI** for the Roadrunner
Flight Test System and its associated tooling.

## Why Archived?

The primary operator interface is now the **web GUI** (`ws_server.py` +
`web/`). The PyQt5 desktop GUI was the original v1-v4 interface, fully
replaced by the React+WebSocket stack in v5.

The web GUI provides:

- Same three-column test layout (UUT table, vehicle status, IBIT display)
- Live telemetry via WebSocket (no Qt signal/slot complexity)
- Cross-platform browser access (no Python GUI dependency on target machines)
- Clean separation from domain logic (zero `ui/*` imports in `vehicle/`,
  `testing/`, `hardware/`, or `sim/`)

The desktop GUI code is preserved here for:

- **Reference** — the widget decomposition and Qt signal wiring are
  useful historical context
- **Reusability** — individual widgets (especially `debug_console.py`
  and the state primitives) could be repurposed
- **Fallback** — in case the web stack has a catastrophic issue and
  the Qt GUI needs to be reinstated (it still works)

## Contents

```
archive/desktop_gui/
├── main.py                     # PyQt5 entry point (QApplication)
├── run_sim.py                  # Launches Qt GUI + SITL together
├── ui/                         # PyQt5 widget tree
│   ├── main_window.py          # Top-level QMainWindow
│   ├── theme.py                # Dark theme stylesheet
│   ├── command_server.py       # TCP command server for remote control
│   ├── qt_adapter.py           # Qt signal bridge for non-Qt callbacks
│   ├── widgets/                # 13 widget modules
│   │   ├── uut_table.py
│   │   ├── status.py
│   │   ├── ibit_display.py
│   │   ├── actuator_feedback.py
│   │   ├── log_widget.py
│   │   ├── controls.py
│   │   ├── debug_console.py
│   │   ├── header.py
│   │   ├── alerts.py
│   │   ├── telemetry_panel.py
│   │   ├── setup.py
│   │   ├── progress.py
│   │   ├── dialogs.py
│   │   └── primitives.py
│   └── __init__.py
├── tests/                      # Desktop-GUI-specific tests
│   ├── functional_test.py      # 17 functional tests (PyQt5 launch + E2E)
│   ├── test_gui_live.py        # Live Qt GUI smoke test
│   ├── test_permutations_gui.py # Operator permutation testing
│   ├── soak_test_24h.py        # 24-hour stability soak
│   ├── edge_case_tests.py      # 29 edge cases (Windows paths hardcoded)
│   └── debug_edge_cases.py     # 22 debug mode tests (Windows paths hardcoded)
└── tools/                      # Remote-control and verification tools
    ├── click_start.py          # TCP control client for the Qt GUI
    ├── analyze_screenshots.py  # Screenshot metadata analyzer
    ├── gui_test.py             # Automated Qt GUI driver
    ├── gui_verify.py           # GUI correctness verification
    ├── gui_sitl_verify.py      # GUI + SITL verification
    └── operator_test.py        # Operator-flow simulation
```

## How to Run (If Needed)

From the project root (not the archive directory):

```bash
# Desktop GUI with real hardware
python archive/desktop_gui/main.py

# Desktop GUI with SITL simulation
python archive/desktop_gui/run_sim.py
```

These scripts expect the domain packages (`vehicle/`, `testing/`,
`hardware/`, `sim/`) to be importable from the project root, which they
still are — those packages were NOT archived.

## What Stays Active (Not Archived)

All of the following remain in the project root and are still the active
codebase:

- `ws_server.py` — Web GUI backend (WebSocket + HTTP server)
- `start.bat` — One-click launcher for the web GUI
- `web/` — React/TypeScript frontend
- `vehicle/` — Connection, constants, preparation
- `testing/` — Executors, callbacks, recovery, tracker, logger
- `hardware/` — NI-DAQmx relay controller
- `sim/` — Pandion vehicle simulator (SITL)
- `tests/test_web_gui_e2e.py` — Headless Web GUI V&V (27/27 passing)
- `tests/new_user_walkthrough.py` — Operator-perspective walkthrough
- `tests/test_sitl.py` — SITL integration tests
- `tests/web_e2e_test.py` — Web-specific E2E
- `tests/test_permutations.py` — Domain-level permutation tests (no GUI)
- `tests/vv/` — Headed Playwright V&V suite

## History

- **v1-v4**: PyQt5 desktop GUI was the only operator interface
- **v5.0**: Web GUI added as parallel interface
- **v5.x** *(this archive)*: Web GUI promoted to primary, desktop GUI archived

## Archived Date

2026-04-19
