# Architecture

> **Note:** the primary operator interface is now the **web GUI**
> (`ws_server.py` + `web/`). The PyQt5 desktop GUI described in some
> layer diagrams below has been archived to `archive/desktop_gui/`.
> The backend layers (`rr_test/execution/`, `rr_test/vehicle/`,
> `rr_test/hardware/`, `rr_test/sim/`) remain shared between the
> retired desktop GUI and the current web GUI.


## Overview

Production-grade automated reliability test system for the Roadrunner UAV flight controller actuation subsystem. Three major components:

1. **Test Software** — PyQt5 operator console that connects to vehicles over UDP MAVLink and runs IBIT / Flight Profile Playback tests
2. **SITL Simulator** — Firmware-accurate vehicle simulator for development and validation without hardware
3. **Automated Test Tools** — TCP remote control, headless screenshot capture, parameterized test suites

## Layer Architecture

```
┌─────────────────────────────────────────────────────┐
│  ui/                     GUI Layer (PyQt5)          │
│  main_window.py          Operator console           │
│  widgets.py              Reusable components        │
│  command_server.py       TCP remote control          │
│  theme.py                Dark theme stylesheet       │
├─────────────────────────────────────────────────────┤
│  rr_test/execution/                Test Execution Layer        │
│  executor.py             IBIT + Playback executors  │
│  logger.py               Telemetry CSV logging      │
├─────────────────────────────────────────────────────┤
│  rr_test/vehicle/                Vehicle Communication       │
│  constants.py            Enums, constants (SSoT)    │
│  connection.py           MAVLink UDP + UUT model    │
│  preparation.py          State machine management    │
├─────────────────────────────────────────────────────┤
│  rr_test/hardware/               Hardware Abstraction        │
│  daq.py                  NI-DAQmx relay control     │
├─────────────────────────────────────────────────────┤
│  rr_test/sim/                    SITL Simulator (standalone) │
│  vehicle.py              State machine + IBIT       │
│  telemetry.py            12 MAVLink message types   │
│  models/                 Servo, battery, monitors   │
└─────────────────────────────────────────────────────┘
```

**Dependency rules:**
- `archive/desktop_gui/ui/` (deprecated) imports from `rr_test/execution/`, `rr_test/vehicle/`, `rr_test/hardware/`
- `rr_test/execution/` imports from `rr_test/vehicle/` (never from `archive/desktop_gui/ui/` (deprecated))
- `rr_test/vehicle/` imports nothing from other project packages
- `rr_test/hardware/` imports nothing from other project packages
- `rr_test/sim/` imports enums from `vehicle/constants` but is otherwise standalone

## Constants — Single Source of Truth

`rr_test/vehicle/constants.py` defines all enums, lookup tables, and named constants used throughout the codebase:

| What | Where | Example |
|------|-------|---------|
| Actuation modes | `ActuationMode` IntEnum | `ActuationMode.IBIT`, `.OPERATE` |
| IBIT substates | `IBITSubstate` IntEnum | `IBITSubstate.ELEVONS`, `.COMPLETE` |
| Flight regimes | `FlightRegime` IntEnum | `FlightRegime.GROUND_ARMED` |
| MAVLink message types | `MsgType` class | `MsgType.ACTUATION_SYS_STATUS` |
| UUT status values | `UUTStatus` class | `UUTStatus.READY`, `.FAILED_PERMANENT` |
| Test mode identifiers | `TestMode` class | `TestMode.IBIT`, `.PLAYBACK` |
| Mistracking flags | `MISTRACKING_FLAG_NAMES` dict | Bitmask → surface name |
| Timeouts and thresholds | `DEFAULT_*` constants | `DEFAULT_IBIT_TIMEOUT = 300.0` |

The sim layer imports these via `sim/config/defaults.py`, which creates backward-compatible aliases (e.g., `IBITSubstate.SETTLE` → production `IBITSubstate.WAIT_FOR_SETTLE`).

## Test Sequence (Single UUT)

```
1. CONNECT (relay OFF)
   MAVLink UDP connection + GCS heartbeat at 1 Hz
   │
2. STATE CAPTURE
   Query USE_NEST, armed state, actuation mode, safety monitors
   │
3. PRE-FLIGHT PREPARATION
   Disable USE_NEST → ARM (clear monitors iteratively) →
   Wait for OPERATE → Clear monitors → Enter PLAYBACK →
   Clear monitors → Enter IBIT
   │
4. ENABLE RELAY (apply load)
   │
5. EXECUTE IBIT
   Monitor substates: BEGIN → SETTLE → ELEVONS → RUDDERS → TVC → COMPLETE
   Detect completion by mode transition: IBIT → OPERATE
   Evaluate mistracking bitmask for PASS/FAIL
   │
6. DISABLE RELAY (remove load)
   │
7. RESTORE STATE
   Ensure OPERATE → Clear overrides → DISARM (if needed) → OFF
   │
8. VERIFY
   Compare final state to initial capture
   │
9. NEXT UUT (or batch complete → generate report)
```

## Threading Model

```
Main Thread (Qt Event Loop)
├── UI updates, user interaction, timer callbacks
│
Test Executor Thread (QThread)
├── Runs complete test sequence per UUT
├── Emits Qt signals for UI updates
│
Background Workers (daemon threads, spawned by executor)
├── Heartbeat sender        1 Hz GCS heartbeat
├── Telemetry receiver      Processes incoming MAVLink messages
├── Statistics updater      Metrics every 2 seconds
├── Connection health       Checks heartbeat reception
├── Log size monitor        Tracks CSV file growth
└── Test duration monitor   Updates elapsed time display
```

**Thread safety:** All MAVLink `recv_match`/`send` calls go through `master_lock`. GUI updates flow through `pyqtSignal` from worker threads to the main thread.

## SITL Simulator

The sim implements firmware-accurate behavior from reading the actual Pandion source (`actuation.c`):

- **State machine**: OFF → OPERATE → PLAYBACK → IBIT with proper transition rules
- **IBIT profiles**: `ibit_linear_function()` triangle waves for elevons/rudders, circular/square patterns for TVC
- **Mistracking detection**: 500 cdeg threshold, 5-cycle consecutive counter for TVC, instant for elevons/rudders
- **Phase timing**: SETTLE=500ms, ELEVON=5000ms, RUDDERS=10000ms, TVC=5000ms
- **Servo dynamics**: First-order lag, rate limiting, thermal protection
- **Battery model**: 7S LiPo with voltage sag under load
- **Monitor system**: Boot monitors, post-ARM monitors, override/clear commands
- **Telemetry gating**: Vehicle only sends telemetry after first GCS heartbeat
- **Fault injection**: 10 pre-built scenarios (HEALTHY, ELEVON_FAIL, TVC_FAIL, etc.)

The sim uses `udpin:0.0.0.0:PORT` (binds and listens) while the test software uses `udpout:127.0.0.1:PORT` (patched at runtime by `run_sim.py`). This avoids Windows `WinError 10054` socket poisoning.

## Key Design Decisions

**Why PLAYBACK before IBIT?**
Vehicle firmware requires OPERATE → PLAYBACK → IBIT. Direct OPERATE → IBIT is not permitted.

**Why continuous monitor clearing?**
Monitors can set asynchronously. Clearing once may not be sufficient. Continuous clearing for 5 seconds ensures all are cleared before mode transition.

**Why detect IBIT completion by mode transition?**
The vehicle may run multiple IBIT cycles. Substate 5 (COMPLETE) may appear multiple times. Only mode transition IBIT → OPERATE confirms true completion.

**Why does the sim never modify production code?**
`run_sim.py` patches `connect_to_vehicle` at runtime to bypass the loopback IP check and use `udpout`. Production code in `rr_test/vehicle/`, `rr_test/execution/`, `rr_test/hardware/`, and `archive/desktop_gui/ui/` (deprecated) is never changed to accommodate the simulator.

## Safety Features

1. **Relay control**: All relays LOW on startup, shutdown, error, and emergency stop. 5-attempt retry with verification on relay disable.
2. **Connection monitoring**: Heartbeat timeout detection (3s), DAQ health checks every 60s.
3. **State management**: Vehicle restored to original state after every test. Monitors cleared before disarm.
4. **Failure handling**: Up to 3 retries per UUT. Permanently failed UUTs skipped. Emergency stop instantly disables all relays.
5. **Sleep prevention**: Windows `SetThreadExecutionState` prevents system sleep during long tests.
