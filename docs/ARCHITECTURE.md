# Architecture

## Overview

The test system has 5 layers. Data flows top-to-bottom for commands,
bottom-to-top for telemetry:

```
┌─────────────────────────────────────────────┐
│  Web GUI (React + TypeScript)               │  web/src/
│  Browser at http://localhost:18890          │
└────────────────────┬────────────────────────┘
                     │ WebSocket (ws://localhost:18889)
                     │ JSON messages: cmd.* (down), telemetry.* (up)
┌────────────────────┴────────────────────────┐
│  Server (rr_test/server/)                   │
│  app_state.py    — shared mutable state     │
│  broadcaster.py  — WS push to all clients   │
│  handlers.py     — 14 cmd.* handlers        │
│  callbacks.py    — executor → WS bridge     │
│  server.py       — HTTP + WS bootstrap      │
└────────────────────┬────────────────────────┘
                     │ Python callbacks (ExecutorCallbacks)
                     │ Runs on a background thread per UUT
┌────────────────────┴────────────────────────┐
│  Execution (rr_test/execution/)             │
│  ibit_executor.py     — IBIT test runner    │
│  playback_executor.py — Playback streamer   │
│  base_executor.py     — shared mixin        │
│  recovery.py          — 3-strike + classify │
│  logger.py            — events.csv + telem  │
└───────┬──────────────────────┬──────────────┘
        │                      │
┌───────┴──────────┐  ┌───────┴──────────┐
│ Vehicle           │  │ Hardware          │
│ (rr_test/vehicle/)│  │ (rr_test/hardware)│
│ connection.py     │  │ daq.py — NI-DAQmx │
│ constants.py      │  │ relay control     │
│ preparation.py    │  └──────────────────┘
│ ARM/DISARM/modes  │
└───────┬──────────┘
        │ UDP MAVLink (Pandion dialect 102, port 13002)
┌───────┴──────────────────────────────────────┐
│  Roadrunner Vehicle (real or SITL sim)        │
│  SITL: rr_test/sim/vehicle.py                │
└──────────────────────────────────────────────┘
```

## Reading order (for a new developer)

1. **`rr_test/vehicle/constants.py`** — all enums, mode IDs, servo limits,
   monitor IDs.  This is the single source of truth that everything else
   references.

2. **`rr_test/vehicle/connection.py`** — how we connect to a vehicle via
   UDP MAVLink.  `connect_to_vehicle()` is the entry point.  `UUT` is the
   data model for a unit under test.

3. **`rr_test/execution/base_executor.py`** — the shared mixin that all
   test executors inherit from.  Handles connection, heartbeat, relay,
   dispatch worker, emergency disable.

4. **`rr_test/execution/ibit_executor.py`** — the IBIT test runner.
   `run()` is the entry point.  Calls preparation → ARM → mode transitions
   → IBIT monitor loop → evaluate → cleanup.

5. **`rr_test/execution/recovery.py`** — failure classification.
   `classify(error_message)` returns a `RecoveryDecision` that tells the
   batch loop whether to retry, skip, reconnect, or wait.

6. **`rr_test/server/handlers.py`** — the 14 WebSocket command handlers.
   `_run_batch()` is the round-robin batch loop.  This is where
   pass/fail tracking and 3-strike logic lives.

7. **`rr_test/server/callbacks.py`** — `wire_callbacks()` bridges executor
   events (on_armed_state, on_actuator_feedback, on_ibit_state, etc.) to
   WebSocket broadcasts that the React frontend reducer consumes.

8. **`web/src/hooks/use-websocket.ts`** — the React reducer.  Every
   WebSocket event type has a `case` here that updates the UI state.

## Threading model

During an active batch test, these threads are running per UUT:

```
Main thread (asyncio)     — WebSocket server + HTTP server + batch ticker
Batch thread              — _run_batch() round-robin loop
  Per-UUT (inside batch):
    Heartbeat thread      — 1 Hz GCS heartbeat sender
    Dispatch thread       — recv loop, routes messages to per-type queues
    Health monitor thread — checks heartbeat age every 5s
```

All MAVLink sends go through `master_lock`.  The dispatch thread is the
sole reader (no lock needed for recv).  UI callbacks use
`asyncio.run_coroutine_threadsafe` to bridge from the batch thread to
the asyncio event loop.

## Key design decisions

- **Relays are test LOAD relays, not vehicle power.**  The vehicle is
  powered by a separate bench supply.  Relay ON = actuators under load.
  Relay OFF = no load.  The test software cannot power-cycle the vehicle.

- **100 Hz playback uses absolute-time scheduling** to prevent drift.
  Frame N's target time is `start + N * 10ms`, not `last_frame + 10ms`.

- **IBIT completion is detected by mode transition** (IBIT→OPERATE), not
  by substate reaching COMPLETE.  The firmware may zero the mistracking
  bitmask on the transition message, so we OR-accumulate flags throughout.

- **Recovery manager classifies failures** into SOFT (auto-retry), HARD
  (skip UUT), and FATAL (counts toward 3-strike permanent skip).  Only
  FATAL failures increment `consecutive_failures`.

- **`RR_SITL_MODE=1` env var** enables loopback + udpout for SITL.
  Must be set before importing `rr_test.execution`.  Production never
  sets this.

## Logs

```
logs/<date>/<serial>/events.csv       — one row per test event
logs/<date>/<serial>/telemetry.csv    — 5 Hz servo data during test
errors/error_log.jsonl                — persistent error log (rotates at 10 MB)
```

## Firmware reference

All timing constants and thresholds are from the Pandion firmware source
(`pandion_roadrunner/vehicle/actuation/actuation.c`).  See
`docs/TEST_FLOW.md` for the complete timing table.
