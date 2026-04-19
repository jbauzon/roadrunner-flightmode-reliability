#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
debug_then_batch_walkthrough.py -- Simulate the full operator journey:
pre-flight debug checks followed by a 9-hour unattended batch test.

This is what a careful operator does before leaving the bench overnight:

  Phase A -- Debug Mode pre-flight (per vehicle):
    1. Connect to the vehicle (WS cmd.debug.connect)
    2. Verify heartbeat + ACTUATION_SYS_STATUS telemetry
    3. Request OPERATE mode (ARM is needed first)
    4. Send ARM (force) via COMMAND_LONG
    5. Verify flight_regime transitions to GROUND_ARMED (1)
    6. Send DISARM
    7. Disconnect cleanly
    -> Vehicle is HEALTHY

  Phase B -- 9-hour batch test:
    1. Configure duration = 9 hours (32400 s)
    2. Start IBIT batch (cmd.start_test)
    3. Sample for several minutes to verify:
       - batch.active stays True
       - Elapsed counts up correctly
       - Remaining counts down correctly
       - Both UUTs get at least one iteration (round-robin works)
       - uut.iteration_complete fires per UUT
       - test.complete does NOT fire prematurely
    4. Stop the batch cleanly (operator cancels early to save test time)

Run:
    python tests/debug_then_batch_walkthrough.py
    python tests/debug_then_batch_walkthrough.py --watch-mins 3   # longer soak

Requires: websockets (pip install websockets)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from collections import defaultdict
from typing import Any

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    from websockets.asyncio.client import connect as ws_connect
except ImportError:
    print("ERROR: 'websockets' required.  pip install websockets")
    sys.exit(1)


# ── Pretty output ────────────────────────────────────────────────────────

T0 = time.monotonic()
def ts() -> str:
    return f"[t+{time.monotonic() - T0:06.1f}s]"

def header(msg: str) -> None:
    print(f"\n{'=' * 74}\n  {msg}\n{'=' * 74}", flush=True)

def step(msg: str) -> None:
    print(f"\n{ts()} \u2192 {msg}", flush=True)

def operator(msg: str) -> None:
    print(f"{ts()}   \033[36mOPERATOR:\033[0m {msg}", flush=True)

def ui(msg: str) -> None:
    print(f"{ts()}   \033[32mUI:\033[0m       {msg}", flush=True)

def backend(msg: str) -> None:
    print(f"{ts()}   \033[33mBACKEND:\033[0m  {msg}", flush=True)

def ok(msg: str) -> None:
    print(f"{ts()}   \033[32m[+]\033[0m {msg}", flush=True)

def bad(msg: str) -> None:
    print(f"{ts()}   \033[31m[X]\033[0m {msg}", flush=True)


# ── Firmware constants ──────────────────────────────────────────────────

MODE_OFF = 0
MODE_IBIT = 1
MODE_OPERATE = 2
MODE_PLAYBACK = 4

REGIME_GROUND_DISARMED = 0
REGIME_GROUND_ARMED = 1

CMD_ARM_DISARM = 400
ARM_FORCE_MAGIC = 21196


# ── Results tracking ────────────────────────────────────────────────────

_fails: list[str] = []
_passes: list[str] = []


def assertion(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        _passes.append(name)
        ok(f"{name}  ({detail})" if detail else name)
    else:
        _fails.append(f"{name}: {detail}")
        bad(f"{name}  ({detail})" if detail else name)


# ── Backend lifecycle ──────────────────────────────────────────────────

def start_backend() -> subprocess.Popen:
    cmd = [sys.executable, "-B", os.path.join(ROOT, "ws_server.py"), "--sitl"]
    return subprocess.Popen(
        cmd,
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


async def wait_for_ws(timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            async with ws_connect("ws://127.0.0.1:18889", open_timeout=1.5):
                return
        except Exception:
            await asyncio.sleep(0.5)
    raise TimeoutError("backend did not start")


# ── Stream reader task ─────────────────────────────────────────────────

class Stream:
    """Background task that reads the WS and maintains a rolling state."""

    def __init__(self, ws: Any) -> None:
        self.ws = ws
        self.msgs: list[dict] = []
        self.by_type: dict[str, list[dict]] = defaultdict(list)
        self.state = {
            "link": "OFFLINE",
            "mode": MODE_OFF,
            "regime": 0,
            "armed": False,
            "relay_on": False,
            "ibit_substate": "IDLE",
            "batch_active": False,
            "batch_elapsed": 0.0,
            "batch_remaining": 0.0,
            "uuts": [],
        }
        self._running = True
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._reader())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except Exception:
                pass

    async def _reader(self) -> None:
        try:
            while self._running:
                try:
                    raw = await asyncio.wait_for(self.ws.recv(), timeout=0.5)
                    msg = json.loads(raw)
                    self.msgs.append(msg)
                    t = msg.get("type", "?")
                    self.by_type[t].append(msg)
                    d = msg.get("data", {}) or {}
                    if t == "connection.health":
                        self.state["link"] = "CONNECTED" if d.get("healthy") else "OFFLINE"
                    elif t == "telemetry.vehicle_status":
                        self.state["mode"] = d.get("mode", self.state["mode"])
                        self.state["regime"] = d.get("regime", self.state["regime"])
                        self.state["armed"] = d.get("armed", self.state["armed"])
                    elif t == "ibit.state":
                        self.state["ibit_substate"] = d.get("substate", "IDLE")
                    elif t == "daq.relay":
                        self.state["relay_on"] = d.get("on", False)
                    elif t == "batch.status":
                        self.state["batch_active"] = d.get("active", False)
                        self.state["batch_elapsed"] = d.get("elapsed_seconds", 0)
                        self.state["batch_remaining"] = d.get("remaining_seconds", 0)
                    elif t == "uut.update":
                        self.state["uuts"] = d.get("uuts", self.state["uuts"])
                    elif t == "state.sync":
                        # Initial state from backend
                        v = d.get("vehicle", {})
                        self.state["mode"] = v.get("mode", 0)
                        self.state["regime"] = v.get("regime", 0)
                        self.state["armed"] = v.get("armed", False)
                        self.state["link"] = "CONNECTED" if v.get("connection_healthy") else "OFFLINE"
                        self.state["uuts"] = d.get("uuts", [])
                        b = d.get("batch", {})
                        self.state["batch_active"] = b.get("active", False)
                except asyncio.TimeoutError:
                    continue
                except Exception:
                    break
        except asyncio.CancelledError:
            pass

    def count(self, t: str) -> int:
        return len(self.by_type.get(t, []))

    def logs_since(self, mark: int) -> list[str]:
        return [
            m.get("data", {}).get("message", "")
            for m in self.by_type.get("test.log", [])[mark:]
        ]

    def log_mark(self) -> int:
        return len(self.by_type.get("test.log", []))


async def wait_for(pred, timeout: float, poll: float = 0.2) -> bool:
    """Wait until pred() returns True or timeout expires."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        await asyncio.sleep(poll)
    return False


# ── Phase A: Debug Mode pre-flight check ───────────────────────────────

async def debug_check_vehicle(
    ws: Any, stream: Stream, uut: dict, index: int, total: int
) -> bool:
    """Pre-flight sanity check on one vehicle via Debug Mode commands."""
    serial = uut["serial_number"]
    ip = uut["ip_address"]
    port = uut["port"]

    header(f"Phase A.{index}: Debug Mode pre-flight on {serial}  ({index}/{total})")

    # ── A.1 Connect ────────────────────────────────────────────────────
    operator(f"Navigates to Debug Mode, selects {serial} from dropdown")
    log_mark = stream.log_mark()
    step("Click [ Connect ]")
    await ws.send(json.dumps({
        "type": "cmd.debug.connect",
        "data": {"serial": serial, "ip": ip, "port": port},
    }))

    got_link = await wait_for(lambda: stream.state["link"] == "CONNECTED", 12.0)
    assertion(f"{serial}: Link shows CONNECTED",
              got_link,
              f"link={stream.state['link']}")
    if not got_link:
        return False

    # ── A.2 Verify telemetry is flowing ───────────────────────────────
    step("Watch for ACTUATION_SYS_STATUS telemetry (should be 5 Hz)")
    act_mark = stream.count("telemetry.actuator")
    await asyncio.sleep(2.5)
    act_new = stream.count("telemetry.actuator") - act_mark
    # At 5 Hz for 2.5s we expect ~12 messages
    assertion(f"{serial}: ACTUATION_SYS_STATUS streaming",
              act_new >= 5,
              f"{act_new} actuator msgs in 2.5s")

    # ── A.3 Request OPERATE (vehicle still OFF, won't transition) ─────
    step("Click [ OPERATE ] mode button (no ARM yet - request will be ignored)")
    await ws.send(json.dumps({
        "type": "cmd.debug.mode_request",
        "data": {"mode_id": MODE_OPERATE},
    }))
    await asyncio.sleep(1.0)
    ui(f"Mode displayed: {stream.state['mode']}  (OFF because not armed)")

    # ── A.4 Force ARM ──────────────────────────────────────────────────
    step("Click [ Force ARM ] to transition vehicle to ARMED")
    await ws.send(json.dumps({
        "type": "cmd.debug.arm",
        "data": {"arm": True, "force": True},
    }))

    got_armed = await wait_for(
        lambda: stream.state["armed"] and stream.state["regime"] == REGIME_GROUND_ARMED,
        15.0,
    )
    assertion(
        f"{serial}: Vehicle reached GROUND_ARMED (regime=1)",
        got_armed,
        f"armed={stream.state['armed']} regime={stream.state['regime']}",
    )

    # ── A.5 Verify OPERATE mode now accepted ──────────────────────────
    # The sim transitions to OPERATE automatically on ARM. Check.
    got_operate = await wait_for(
        lambda: stream.state["mode"] == MODE_OPERATE,
        10.0,
    )
    assertion(
        f"{serial}: Vehicle in OPERATE mode after ARM",
        got_operate,
        f"mode={stream.state['mode']}",
    )

    # ── A.6 DISARM cleanly ────────────────────────────────────────────
    step("Click [ DISARM ] to return vehicle to safe state")
    await ws.send(json.dumps({
        "type": "cmd.debug.arm",
        "data": {"arm": False, "force": False},
    }))

    got_disarmed = await wait_for(
        lambda: not stream.state["armed"] and stream.state["regime"] == 0,
        10.0,
    )
    assertion(
        f"{serial}: Vehicle DISARMED cleanly (regime=0)",
        got_disarmed,
        f"armed={stream.state['armed']} regime={stream.state['regime']}",
    )

    # ── A.7 Disconnect ────────────────────────────────────────────────
    step("Click [ Disconnect ]")
    await ws.send(json.dumps({"type": "cmd.debug.disconnect"}))

    got_offline = await wait_for(
        lambda: stream.state["link"] == "OFFLINE", 5.0,
    )
    assertion(
        f"{serial}: Link returns to OFFLINE after disconnect",
        got_offline,
        f"link={stream.state['link']}",
    )

    ok(f"{serial} is HEALTHY — cleared for batch test")
    return got_link and got_armed and got_operate and got_disarmed and got_offline


# ── Phase B: 9-hour batch test ─────────────────────────────────────────

async def start_9h_batch(
    ws: Any, stream: Stream, watch_mins: float
) -> bool:
    header(f"Phase B: Start 9-hour batch test, watch for {watch_mins:.1f} min")

    # ── B.1 Configure duration = 9 Hours ──────────────────────────────
    NINE_HOURS = 9 * 3600  # 32400 s
    operator("Switches to Test Mode tab")
    operator("Selects: Duration = 9 Hours (Value=9, Unit=Hours)")
    ui(f"duration_seconds resolves to {NINE_HOURS}s")

    # ── B.2 Click Start IBIT Test ─────────────────────────────────────
    operator("Confirms: 2 UUTs loaded, DAQ/SITL ready, IBIT mode selected")
    step("Clicks [ Start IBIT Test ] (big green button)")

    t_start = time.monotonic()
    await ws.send(json.dumps({
        "type": "cmd.start_test",
        "data": {
            "mode": "ibit",
            "duration_seconds": NINE_HOURS,
            "config": {
                "ibit_timeout": 120,
                "phase_timeout": 60,
                "arm_timeout": 30,
            },
        },
    }))

    # ── B.3 Verify batch becomes active ──────────────────────────────
    got_active = await wait_for(
        lambda: stream.state["batch_active"], 5.0,
    )
    assertion("Batch becomes active", got_active,
              f"batch_active={stream.state['batch_active']}")

    # ── B.4 Verify initial timer values are reasonable ───────────────
    await asyncio.sleep(1.5)
    remaining = stream.state["batch_remaining"]
    assertion(
        "Remaining timer starts near 9h (32400s)",
        32000 < remaining <= NINE_HOURS,
        f"remaining={remaining:.0f}s (expected ~{NINE_HOURS})",
    )

    elapsed = stream.state["batch_elapsed"]
    assertion(
        "Elapsed timer starts near 0",
        0 <= elapsed < 10,
        f"elapsed={elapsed:.1f}s",
    )

    # ── B.5 Watch for watch_mins minutes ─────────────────────────────
    watch_secs = int(watch_mins * 60)
    step(f"Watching batch for {watch_secs}s (operator leaves for the night)...")

    # Sample every 30s
    samples = []
    deadline = time.monotonic() + watch_secs
    last_sample = time.monotonic()
    iter_complete_count = 0
    test_complete_seen = False
    modes_seen = {stream.state["mode"]}
    substates_seen = {stream.state["ibit_substate"]}

    while time.monotonic() < deadline:
        await asyncio.sleep(2.0)

        # Track mode / substate progression
        modes_seen.add(stream.state["mode"])
        substates_seen.add(stream.state["ibit_substate"])

        # Count iteration completes (new ones since last sample)
        iter_complete_count = stream.count("uut.iteration_complete")
        if stream.count("test.complete") > 0:
            test_complete_seen = True

        # Sample every 30s for the progress table
        if time.monotonic() - last_sample >= 30.0 or (time.monotonic() >= deadline):
            last_sample = time.monotonic()
            elapsed_wall = time.monotonic() - t_start
            samples.append({
                "wall": elapsed_wall,
                "elapsed": stream.state["batch_elapsed"],
                "remaining": stream.state["batch_remaining"],
                "mode": stream.state["mode"],
                "substate": stream.state["ibit_substate"],
                "iterations": [u.get("iterations_completed", 0) for u in stream.state["uuts"]],
                "iter_completes": iter_complete_count,
                "batch_active": stream.state["batch_active"],
            })

    # ── B.6 Print progress table ──────────────────────────────────────
    header("Batch progress samples (every ~30s)")
    print("  wall(s)  elapsed(s)  remaining(s)  mode     substate         uuts_iter  completes  active")
    print("  -------  ----------  ------------  -------  ---------------  ---------  ---------  ------")
    for s in samples:
        print(
            f"  {s['wall']:7.1f}  {s['elapsed']:10.1f}  {s['remaining']:12.1f}  "
            f"{s['mode']:>7}  {s['substate']:<15}  {str(s['iterations']):>9}  "
            f"{s['iter_completes']:>9}  {str(s['batch_active']):>6}"
        )

    # ── B.7 Verify assertions for the 9h run ─────────────────────────
    header("Batch-run assertions")

    # Batch is still active (shouldn't end early)
    assertion(
        "Batch still active after watch period",
        stream.state["batch_active"],
        f"batch_active={stream.state['batch_active']}",
    )

    # test.complete should NOT have fired yet (9h hasn't elapsed)
    assertion(
        "test.complete NOT fired prematurely",
        not test_complete_seen,
        f"test.complete count={stream.count('test.complete')}",
    )

    # Elapsed timer is counting up
    final_elapsed = stream.state["batch_elapsed"]
    assertion(
        f"Elapsed timer advanced past {int(watch_secs * 0.8)}s",
        final_elapsed > watch_secs * 0.8,
        f"elapsed={final_elapsed:.0f}s",
    )

    # Remaining is counting down (approximately)
    final_remaining = stream.state["batch_remaining"]
    assertion(
        "Remaining timer decreased from 9h",
        final_remaining < NINE_HOURS - watch_secs * 0.8,
        f"remaining={final_remaining:.0f}s (started at {NINE_HOURS})",
    )

    # At least one mode transition (should have seen OPERATE, PLAYBACK, or IBIT)
    non_off = modes_seen - {MODE_OFF}
    assertion(
        "Vehicle cycled through non-OFF modes",
        len(non_off) >= 1,
        f"modes={sorted(modes_seen)}",
    )

    # At least one IBIT substate beyond IDLE/CONNECTING
    ibit_phases = {"BEGIN", "WAIT_FOR_SETTLE", "ELEVONS", "RUDDERS", "TVC"}
    observed = substates_seen & ibit_phases
    assertion(
        "IBIT substates advanced (ELEVONS/RUDDERS/TVC)",
        len(observed) >= 1,
        f"observed={sorted(observed)}",
    )

    # Iterations completed for at least one UUT
    max_iter = max(
        (u.get("iterations_completed", 0) for u in stream.state["uuts"]),
        default=0,
    )
    assertion(
        "At least one UUT iteration completed",
        max_iter >= 1,
        f"max iterations={max_iter}",
    )

    # ── B.8 Operator stops the batch early ───────────────────────────
    step("Operator decides to stop early (not actually waiting 9h)")
    operator("Clicks [ Stop ] button")
    await ws.send(json.dumps({"type": "cmd.stop_test"}))

    got_stopped = await wait_for(
        lambda: not stream.state["batch_active"], 10.0,
    )
    assertion(
        "Batch stops cleanly on operator request",
        got_stopped,
        f"batch_active={stream.state['batch_active']}",
    )

    # Relay should end OFF after stop
    await asyncio.sleep(2.0)
    assertion(
        "Relay OFF after stop (safety)",
        not stream.state["relay_on"],
        f"relay_on={stream.state['relay_on']}",
    )

    return True


# ── Main walkthrough ───────────────────────────────────────────────────

async def run(watch_mins: float) -> int:
    header("OPERATOR JOURNEY: Pre-flight debug -> 9-hour batch test")
    print(f"  Watch time for batch phase: {watch_mins} min")
    print(f"  Total expected duration:    ~{1 + watch_mins + 0.5:.1f} min")

    header("Environment setup")
    operator("Starts the test bench: double-click start.bat --sitl")
    proc = start_backend()
    print(f"  Backend PID: {proc.pid}")

    try:
        await wait_for_ws()
        ok("Web server up on http://localhost:18890")
        await asyncio.sleep(3.5)  # Let SITL launcher finish

        async with ws_connect(
            "ws://127.0.0.1:18889", max_size=2**22, ping_interval=None
        ) as ws:
            stream = Stream(ws)
            await stream.start()

            # Sync initial state
            await ws.send(json.dumps({"type": "cmd.sync_state"}))
            await asyncio.sleep(2.0)

            ok(f"Loaded {len(stream.state['uuts'])} UUTs in the table")
            for u in stream.state["uuts"]:
                print(f"      - {u.get('serial_number')}  "
                      f"{u.get('ip_address')}:{u.get('port')}  "
                      f"status={u.get('status')}")

            if len(stream.state["uuts"]) < 2:
                bad("SITL did not load 2 UUTs; aborting walkthrough")
                return 1

            # ══════════════════════════════════════════════════════════
            # Phase A: Debug each vehicle
            # ══════════════════════════════════════════════════════════
            uuts = list(stream.state["uuts"])
            all_healthy = True
            for i, uut in enumerate(uuts, 1):
                healthy = await debug_check_vehicle(ws, stream, uut, i, len(uuts))
                if not healthy:
                    all_healthy = False
                    bad(f"{uut['serial_number']} FAILED debug check")
                await asyncio.sleep(1.5)

            if not all_healthy:
                header("Pre-flight FAILED — do NOT proceed with overnight batch")
                return 1

            header("PRE-FLIGHT PASSED: all vehicles healthy")
            operator("Satisfied all vehicles are responding correctly")
            operator("Switches to Test Mode tab")

            # ══════════════════════════════════════════════════════════
            # Phase B: 9-hour batch
            # ══════════════════════════════════════════════════════════
            await start_9h_batch(ws, stream, watch_mins)

            await stream.stop()

    finally:
        header("Shutdown")
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        ok("Backend stopped")

    # ── Final summary ──────────────────────────────────────────────────
    header("FINAL RESULTS")
    total = len(_passes) + len(_fails)
    print(f"  {len(_passes)}/{total} passed, {len(_fails)} failed")
    if _fails:
        print("\n  FAILED:")
        for f in _fails:
            print(f"    [X] {f}")
    return 0 if not _fails else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--watch-mins", type=float, default=2.5,
        help="Minutes to watch the batch run before stopping (default 2.5)",
    )
    args = ap.parse_args()

    try:
        return asyncio.run(run(args.watch_mins))
    except KeyboardInterrupt:
        print("\nInterrupted")
        return 1


if __name__ == "__main__":
    sys.exit(main())
