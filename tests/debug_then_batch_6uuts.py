#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
debug_then_batch_6uuts.py -- Operator journey with 6 UUTs connected.

Simulates the full workflow on a full 6-vehicle test bench:

  1. Start the web GUI with SITL (ws_server.py --sitl) which brings up
     RR-SIM-001 and RR-SIM-002 by default.
  2. Walkthrough spawns 4 ADDITIONAL sim vehicles in-process
     (RR-SIM-003 through RR-SIM-006) and registers them with the
     backend via cmd.add_uut so they appear in the UUT table.
  3. Phase A -- Debug Mode pre-flight on EACH of the 6 vehicles:
       Connect -> verify telemetry -> Force ARM -> verify GROUND_ARMED
       -> DISARM -> Disconnect
  4. Phase B -- Start IBIT batch with 9-hour duration, watch for
     several minutes to verify round-robin across all 6 UUTs.
  5. Operator stops the batch cleanly.

UUT configuration:
  RR-SIM-001  port 19901  relay 0  PASS
  RR-SIM-002  port 19902  relay 1  FAIL (0xC0 both elevons)
  RR-SIM-003  port 19903  relay 2  PASS
  RR-SIM-004  port 19904  relay 3  PASS
  RR-SIM-005  port 19905  relay 4  FAIL (0x01 upper rudder)
  RR-SIM-006  port 19906  relay 5  PASS

Run:
    python tests/debug_then_batch_6uuts.py
    python tests/debug_then_batch_6uuts.py --watch-mins 5.0

Requires: websockets (pip install websockets)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import threading
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


# ── Pretty output ───────────────────────────────────────────────────────

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


# ── Firmware constants ─────────────────────────────────────────────────

MODE_OFF = 0
MODE_IBIT = 1
MODE_OPERATE = 2
MODE_PLAYBACK = 4

REGIME_GROUND_DISARMED = 0
REGIME_GROUND_ARMED = 1


# ── 6-UUT test bench layout ────────────────────────────────────────────

EXTRA_SIM_CONFIGS = [
    {"serial": "RR-SIM-003", "port": 19903, "relay": 2, "sysid": 3,
     "ibit_pass": True,  "mistracking_flags": 0x00},
    {"serial": "RR-SIM-004", "port": 19904, "relay": 3, "sysid": 4,
     "ibit_pass": True,  "mistracking_flags": 0x00},
    {"serial": "RR-SIM-005", "port": 19905, "relay": 4, "sysid": 5,
     "ibit_pass": False, "mistracking_flags": 0x01},  # Upper rudder
    {"serial": "RR-SIM-006", "port": 19906, "relay": 5, "sysid": 6,
     "ibit_pass": True,  "mistracking_flags": 0x00},
]


# ── Results tracking ──────────────────────────────────────────────────

_fails: list[str] = []
_passes: list[str] = []


def assertion(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        _passes.append(name)
        ok(f"{name}  ({detail})" if detail else name)
    else:
        _fails.append(f"{name}: {detail}")
        bad(f"{name}  ({detail})" if detail else name)


# ── Backend lifecycle ─────────────────────────────────────────────────

def start_backend() -> subprocess.Popen:
    # Kill any leftover backend + sim processes from a previous run
    try:
        subprocess.run(
            ["pkill", "-9", "-f", "ws_server.py"],
            timeout=3, capture_output=True,
        )
        time.sleep(2)
    except Exception:
        pass

    cmd = [sys.executable, "-B", os.path.join(ROOT, "ws_server.py"), "--sitl"]
    return subprocess.Popen(
        cmd, cwd=ROOT,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
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


# ── Extra sim spawner ─────────────────────────────────────────────────

def spawn_extra_sims() -> list:
    """
    Spawn 4 additional SITL vehicles in-process (RR-SIM-003..006).
    They share the walkthrough's Python process with their own UDP sockets.
    """
    # Import here so the SITL path is set before we try to use pymavlink
    from sim.vehicle import PandionVehicleSim

    sims = []
    for cfg in EXTRA_SIM_CONFIGS:
        sim = PandionVehicleSim(
            vehicle_port=cfg["port"],
            sysid=cfg["sysid"],
            ibit_pass=cfg["ibit_pass"],
            mistracking_flags=cfg["mistracking_flags"],
            boot_time_s=2.0,
            ibit_duration_scale=0.5,
            boot_monitors=[0, 1, 2, 3],
        )
        # sim.start() runs the RX loop synchronously — use a thread
        threading.Thread(
            target=sim.start, daemon=True,
            name=f"extra-sim-{cfg['port']}",
        ).start()
        sims.append(sim)
    return sims


# ── Stream reader ─────────────────────────────────────────────────────

class Stream:
    """Background task that reads the WS and maintains rolling state."""

    def __init__(self, ws: Any) -> None:
        self.ws = ws
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


async def wait_for(pred, timeout: float, poll: float = 0.2) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        await asyncio.sleep(poll)
    return False


# ── Phase A: Debug pre-flight per UUT ─────────────────────────────────

async def debug_check_vehicle(
    ws: Any, stream: Stream, uut: dict, index: int, total: int
) -> bool:
    serial = uut["serial_number"]
    ip = uut["ip_address"]
    port = uut["port"]

    print()
    step(f"Phase A.{index}/{total}: Debug pre-flight on {serial} "
         f"(port {port}, relay {uut.get('relay_line', '?')})")

    # A.1 Connect
    await ws.send(json.dumps({
        "type": "cmd.debug.connect",
        "data": {"serial": serial, "ip": ip, "port": port},
    }))

    got_link = await wait_for(lambda: stream.state["link"] == "CONNECTED", 12.0)
    assertion(f"{serial}: Link = CONNECTED",
              got_link, f"link={stream.state['link']}")
    if not got_link:
        return False

    # A.2 Telemetry flowing
    act_mark = stream.count("telemetry.actuator")
    await asyncio.sleep(2.0)
    act_new = stream.count("telemetry.actuator") - act_mark
    assertion(f"{serial}: ACTUATION_SYS_STATUS streaming",
              act_new >= 4,
              f"{act_new} msgs in 2s (expected >=4 @ 5Hz)")

    # A.3 Force ARM
    await ws.send(json.dumps({
        "type": "cmd.debug.arm",
        "data": {"arm": True, "force": True},
    }))

    got_armed = await wait_for(
        lambda: stream.state["armed"]
                and stream.state["regime"] == REGIME_GROUND_ARMED,
        15.0,
    )
    assertion(f"{serial}: reached GROUND_ARMED", got_armed,
              f"armed={stream.state['armed']} regime={stream.state['regime']}")

    # A.4 Verify OPERATE
    got_operate = await wait_for(
        lambda: stream.state["mode"] == MODE_OPERATE, 10.0,
    )
    assertion(f"{serial}: OPERATE mode", got_operate,
              f"mode={stream.state['mode']}")

    # A.5 DISARM
    await ws.send(json.dumps({
        "type": "cmd.debug.arm",
        "data": {"arm": False, "force": False},
    }))

    got_disarmed = await wait_for(
        lambda: not stream.state["armed"] and stream.state["regime"] == 0,
        10.0,
    )
    assertion(f"{serial}: DISARMED cleanly", got_disarmed,
              f"armed={stream.state['armed']} regime={stream.state['regime']}")

    # A.6 Disconnect
    await ws.send(json.dumps({"type": "cmd.debug.disconnect"}))
    got_offline = await wait_for(
        lambda: stream.state["link"] == "OFFLINE", 5.0,
    )
    assertion(f"{serial}: OFFLINE after disconnect",
              got_offline, f"link={stream.state['link']}")

    all_passed = all([got_link, got_armed, got_operate, got_disarmed, got_offline])
    if all_passed:
        ok(f"{serial} HEALTHY")
    else:
        bad(f"{serial} FAILED debug check")
    return all_passed


# ── Phase B: 9-hour batch ─────────────────────────────────────────────

async def start_9h_batch(ws: Any, stream: Stream, watch_mins: float,
                         num_uuts: int) -> bool:
    header(f"Phase B: 9-hour batch across {num_uuts} UUTs, "
           f"watching for {watch_mins:.1f} min")

    NINE_HOURS = 9 * 3600  # 32400 s
    operator("Switches to Test Mode tab")
    operator("Sets Duration = 9 Hours -> 32400 s")
    operator(f"Confirms all {num_uuts} UUTs READY")
    step("Click [ Start IBIT Test ]")

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

    got_active = await wait_for(lambda: stream.state["batch_active"], 5.0)
    assertion("Batch becomes active", got_active,
              f"batch_active={stream.state['batch_active']}")

    await asyncio.sleep(1.5)
    remaining = stream.state["batch_remaining"]
    assertion("Remaining timer starts near 9h",
              32000 < remaining <= NINE_HOURS,
              f"remaining={remaining:.0f}s")

    # Watch phase
    watch_secs = int(watch_mins * 60)
    step(f"Watching for {watch_secs}s — round-robin across {num_uuts} vehicles")

    samples = []
    uuts_seen_testing = set()
    uuts_completed_iter = set()
    modes_seen = set()
    substates_seen = set()
    test_complete_seen = False

    deadline = time.monotonic() + watch_secs
    last_sample = time.monotonic()
    t_start = time.monotonic()

    while time.monotonic() < deadline:
        await asyncio.sleep(2.0)

        modes_seen.add(stream.state["mode"])
        substates_seen.add(stream.state["ibit_substate"])

        if stream.count("test.complete") > 0:
            test_complete_seen = True

        # Track which UUTs have reached TESTING and which have completed iterations
        for u in stream.state["uuts"]:
            if u.get("status") == "TESTING":
                uuts_seen_testing.add(u.get("serial_number"))
            if u.get("iterations_completed", 0) > 0:
                uuts_completed_iter.add(u.get("serial_number"))

        if time.monotonic() - last_sample >= 30.0 or time.monotonic() >= deadline:
            last_sample = time.monotonic()
            elapsed_wall = time.monotonic() - t_start
            iters = [(u.get("serial_number", "?")[-3:],
                      u.get("iterations_completed", 0),
                      u.get("status", "?")[:4])
                     for u in stream.state["uuts"]]
            samples.append({
                "wall": elapsed_wall,
                "elapsed": stream.state["batch_elapsed"],
                "remaining": stream.state["batch_remaining"],
                "iters": iters,
                "completes": stream.count("uut.iteration_complete"),
                "testing_seen": len(uuts_seen_testing),
            })

    # Progress table
    header(f"Batch progress (every ~30s) — {num_uuts} UUTs")
    print("  wall(s)  elapsed(s)  remaining(s)  iterations                                               completes  testing_seen")
    print("  -------  ----------  ------------  ------------------------------------------------------  ---------  ------------")
    for s in samples:
        iter_str = " ".join(f"{sn}:{n}/{st}" for (sn, n, st) in s["iters"])
        print(f"  {s['wall']:7.1f}  {s['elapsed']:10.1f}  {s['remaining']:12.1f}  "
              f"{iter_str:<54}  {s['completes']:>9}  {s['testing_seen']:>12}")

    # Final assertions
    header("Batch assertions")

    assertion("Batch still active after watch period",
              stream.state["batch_active"],
              f"batch_active={stream.state['batch_active']}")

    assertion("test.complete NOT fired prematurely",
              not test_complete_seen,
              f"test.complete count={stream.count('test.complete')}")

    final_elapsed = stream.state["batch_elapsed"]
    assertion(f"Elapsed timer > {int(watch_secs * 0.8)}s",
              final_elapsed > watch_secs * 0.8,
              f"elapsed={final_elapsed:.0f}s")

    final_remaining = stream.state["batch_remaining"]
    assertion("Remaining decreased from 9h",
              final_remaining < NINE_HOURS - watch_secs * 0.5,
              f"remaining={final_remaining:.0f}s")

    non_off = modes_seen - {MODE_OFF}
    assertion("Vehicle cycled through non-OFF modes",
              len(non_off) >= 1,
              f"modes={sorted(modes_seen)}")

    ibit_phases = {"BEGIN", "WAIT_FOR_SETTLE", "ELEVONS", "RUDDERS", "TVC"}
    observed = substates_seen & ibit_phases
    assertion("IBIT substates advanced",
              len(observed) >= 1,
              f"observed={sorted(observed)}")

    max_iter = max((u.get("iterations_completed", 0)
                    for u in stream.state["uuts"]), default=0)
    total_iter = sum((u.get("iterations_completed", 0)
                      for u in stream.state["uuts"]))
    assertion("At least one UUT iteration completed",
              max_iter >= 1,
              f"max={max_iter} total={total_iter}")

    # Round-robin across multiple UUTs:
    # With 6 UUTs and ~45s per iteration, we expect to see multiple distinct
    # UUTs reach TESTING state during a few minutes of observation.
    assertion("Round-robin reached multiple UUTs",
              len(uuts_seen_testing) >= 2,
              f"UUTs seen in TESTING: {sorted(uuts_seen_testing)}")

    # Clean stop
    step("Operator clicks [ Stop ] to end batch early")
    await ws.send(json.dumps({"type": "cmd.stop_test"}))

    got_stopped = await wait_for(
        lambda: not stream.state["batch_active"], 10.0,
    )
    assertion("Batch stops cleanly", got_stopped,
              f"batch_active={stream.state['batch_active']}")

    # Wait up to 15s for relay to go OFF (cleanup with in-flight IBIT
    # can take several seconds to DISARM and release the relay).
    relay_off = await wait_for(
        lambda: not stream.state["relay_on"], 15.0,
    )
    assertion("Relay OFF after stop (safety)",
              relay_off,
              f"relay_on={stream.state['relay_on']}")

    return True


# ── Main ──────────────────────────────────────────────────────────────

async def run(watch_mins: float) -> int:
    header("OPERATOR JOURNEY: 6-UUT bench — Debug pre-flight -> 9h batch")

    header("Environment setup")
    operator("Starts test bench: start.bat --sitl")
    proc = start_backend()
    print(f"  Backend PID: {proc.pid}")

    # Spawn extra sims so the 6-UUT bench is ready before we connect
    print()
    operator("Additional 4 vehicles powered on (RR-SIM-003..006)")
    extra_sims = spawn_extra_sims()
    print(f"  Extra sims started: ports "
          f"{[c['port'] for c in EXTRA_SIM_CONFIGS]}")

    try:
        await wait_for_ws()
        ok("Web server ready on http://localhost:18890")
        await asyncio.sleep(4.0)  # Let SITL finish + extra sims boot

        async with ws_connect(
            "ws://127.0.0.1:18889", max_size=2**22,
            ping_interval=20, ping_timeout=60,
        ) as ws:
            stream = Stream(ws)
            await stream.start()

            await ws.send(json.dumps({"type": "cmd.sync_state"}))
            await asyncio.sleep(2.0)

            # ── Add the 4 extra UUTs to the backend ────────────────
            step("Adding 4 additional UUTs (RR-SIM-003..006) to the table")
            for cfg in EXTRA_SIM_CONFIGS:
                await ws.send(json.dumps({
                    "type": "cmd.add_uut",
                    "data": {
                        "serial_number": cfg["serial"],
                        "ip_address": "127.0.0.1",
                        "port": cfg["port"],
                        "relay_line": cfg["relay"],
                    },
                }))
                await asyncio.sleep(0.2)

            # Wait for UUT table to update
            await wait_for(lambda: len(stream.state["uuts"]) >= 6, 5.0)

            n_uuts = len(stream.state["uuts"])
            assertion(f"UUT table shows all 6 vehicles",
                      n_uuts == 6, f"got {n_uuts}")

            if n_uuts < 6:
                bad("Did not get 6 UUTs in the table — aborting")
                return 1

            print()
            ok("Full 6-UUT test bench loaded")
            for u in stream.state["uuts"]:
                print(f"      - {u.get('serial_number')}  "
                      f"{u.get('ip_address')}:{u.get('port')}  "
                      f"relay={u.get('relay_line')}  "
                      f"status={u.get('status')}")

            # ══════════════════════════════════════════════════════════
            # Phase A: Debug each vehicle
            # ══════════════════════════════════════════════════════════
            header("Phase A: Debug Mode pre-flight across all 6 vehicles")
            operator("Systematically verifying each vehicle responds correctly")

            uuts = list(stream.state["uuts"])
            all_healthy = True
            for i, uut in enumerate(uuts, 1):
                healthy = await debug_check_vehicle(ws, stream, uut, i, len(uuts))
                if not healthy:
                    all_healthy = False
                await asyncio.sleep(1.0)

            if not all_healthy:
                header("PRE-FLIGHT FAILED — do NOT proceed with overnight batch")
                return 1

            header(f"PRE-FLIGHT PASSED: all {len(uuts)} vehicles HEALTHY")
            operator("All 6 vehicles responding correctly, cleared for batch")

            # ══════════════════════════════════════════════════════════
            # Phase B: 9-hour batch
            # ══════════════════════════════════════════════════════════
            await start_9h_batch(ws, stream, watch_mins, len(uuts))
            await stream.stop()

    finally:
        header("Shutdown")
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        ok("Backend stopped")

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
        "--watch-mins", type=float, default=4.0,
        help="Minutes to watch the batch run (default 4.0)",
    )
    args = ap.parse_args()

    try:
        return asyncio.run(run(args.watch_mins))
    except KeyboardInterrupt:
        print("\nInterrupted")
        return 1


if __name__ == "__main__":
    sys.exit(main())
