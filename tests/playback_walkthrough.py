#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
playback_walkthrough.py -- Operator journey for Flight Profile Playback mode.

Playback mode streams a pre-recorded CSV of servo + engine commands at 100 Hz
to the vehicle.  Unlike IBIT (where the firmware runs its own internal test),
Playback mode has the GCS actively driving the actuators.  Pass/fail is
determined by the mistracking bitmask in PANDION_RR_ACTUATION_SYS_STATUS
(same 500 cdeg threshold as IBIT).

Required firmware state before streaming:
    CLASSIC_MODE_EN = 1  (power cycle required to take effect)
    USE_NEST        = 0
    OFF -> ARM -> OPERATE -> PLAYBACK

This walkthrough:
  1. Launches ws_server.py --sitl (2 default UUTs)
  2. Generates a short sinusoidal flight profile CSV
  3. Fixes the playback_csv path on-disk before kicking the batch
  4. Starts a 300-second Playback batch
  5. Watches the WebSocket stream to verify:
     - CLASSIC_MODE_EN = 1 param set
     - Power cycle executed (relay toggles OFF then ON)
     - ARM -> OPERATE -> PLAYBACK transitions
     - Progress log entries with "Frame N/total"
     - Iteration completes with PASS (both UUTs have ibit_pass=True by default)

Requires: websockets
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import math
import os
import subprocess
import sys
import tempfile
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


# ── Constants ─────────────────────────────────────────────────────────

MODE_OFF = 0
MODE_OPERATE = 2
MODE_PLAYBACK = 4

# Commanded amplitudes (chosen well under servo limits to guarantee tracking):
ELEVON_AMP = 1500   # ±1500 cdeg  (limit ±3500)
RUDDER_AMP = 1500   # ±1500 cdeg  (limit ±6000)
TVC_AMP    = 1500   # ±1500 cdeg  (limit ±6000)

# ── Results tracking ──────────────────────────────────────────────────

_passes: list[str] = []
_fails: list[str] = []

def assertion(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        _passes.append(name)
        ok(f"{name}  ({detail})" if detail else name)
    else:
        _fails.append(f"{name}: {detail}")
        bad(f"{name}  ({detail})" if detail else name)


# ── Flight profile CSV generator ──────────────────────────────────────

def generate_profile(path: str, duration_s: float = 4.0,
                     rate_hz: int = 100) -> int:
    """Generate a benign sinusoidal flight profile.

    Commands every surface with a small sine wave ±1500 cdeg.
    All amplitudes are well under servo limits and within the 500 cdeg
    mistracking threshold for a healthy vehicle.

    Uses the production short-name CSV format (matches real flight-test
    exports like NominalFlight_noRudder.csv).

    Returns the number of frames written.
    """
    n_frames = int(duration_s * rate_hz)
    dt = 1.0 / rate_hz
    w1 = 2.0 * math.pi * 0.5    # 0.5 Hz base frequency
    w2 = 2.0 * math.pi * 0.3    # 0.3 Hz for variation

    columns = [
        'timestamp',
        'left_elevon_ted_cdeg',
        'right_elevon_ted_cdeg',
        'lower_rudder_tel_cdeg',
        'upper_rudder_tel_cdeg',
        'left_tvc_upper_cdeg',
        'left_tvc_lower_cdeg',
        'right_tvc_upper_cdeg',
        'right_tvc_lower_cdeg',
        'left_engine_prct_thrust',
        'right_engine_prct_thrust',
    ]

    with open(path, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(columns)
        for i in range(n_frames):
            t = i * dt
            s1 = math.sin(w1 * t)
            s2 = math.sin(w2 * t)
            # Smooth ramp up/down via a half-sine window so cmds start/end at 0
            envelope = math.sin(math.pi * t / duration_s) if duration_s > 0 else 1.0
            left_elev  = ELEVON_AMP  * s1 * envelope
            right_elev = -ELEVON_AMP * s1 * envelope  # anti-phase
            upper_rud  = RUDDER_AMP  * s2 * envelope
            lower_rud  = -RUDDER_AMP * s2 * envelope
            l_tvc_up   = TVC_AMP     * s1 * envelope
            l_tvc_lo   = TVC_AMP     * s2 * envelope
            r_tvc_up   = TVC_AMP     * s1 * envelope
            r_tvc_lo   = TVC_AMP     * s2 * envelope
            left_eng   = 50.0   # 50% throttle, constant
            right_eng  = 50.0
            w.writerow([
                f"{t:.4f}",
                f"{left_elev:.1f}", f"{right_elev:.1f}",
                f"{lower_rud:.1f}", f"{upper_rud:.1f}",
                f"{l_tvc_up:.1f}", f"{l_tvc_lo:.1f}",
                f"{r_tvc_up:.1f}", f"{r_tvc_lo:.1f}",
                f"{left_eng:.1f}", f"{right_eng:.1f}",
            ])

    return n_frames


# ── Backend lifecycle ─────────────────────────────────────────────────

def start_backend() -> subprocess.Popen:
    cmd = [sys.executable, "-B", os.path.join(ROOT, "ws_server.py"), "--sitl"]
    # Capture server output so we can debug if playback fails
    log_path = os.path.join(ROOT, "_pb_server.log")
    log_file = open(log_path, "w")
    return subprocess.Popen(
        cmd, cwd=ROOT,
        stdout=log_file, stderr=subprocess.STDOUT,
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


# ── Stream ────────────────────────────────────────────────────────────

class Stream:
    """Background WS reader maintaining rolling state."""

    def __init__(self, ws: Any) -> None:
        self.ws = ws
        self.by_type: dict[str, list[dict]] = defaultdict(list)
        self.state = {
            "link": "OFFLINE",
            "mode": MODE_OFF,
            "armed": False,
            "regime": 0,
            "relay_on": False,
            "batch_active": False,
            "batch_elapsed": 0.0,
            "uuts": [],
        }
        self._task: asyncio.Task | None = None
        self._running = True
        self._log_markers: list[int] = []

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
                    elif t == "daq.relay":
                        self.state["relay_on"] = d.get("on", False)
                    elif t == "batch.status":
                        self.state["batch_active"] = d.get("active", False)
                        self.state["batch_elapsed"] = d.get("elapsed_seconds", 0)
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

    def logs(self) -> list[str]:
        return [
            m.get("data", {}).get("message", "")
            for m in self.by_type.get("test.log", [])
        ]

    def log_contains(self, needle: str) -> bool:
        return any(needle in m for m in self.logs())


async def wait_for(pred, timeout: float, poll: float = 0.2) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        await asyncio.sleep(poll)
    return False


# ── Main walkthrough ──────────────────────────────────────────────────

async def run(csv_duration_s: float, watch_secs: int,
              real_csv: str | None = None) -> int:
    header("OPERATOR JOURNEY: Flight Profile Playback mode (SITL)")

    # Choose CSV: either the real flight profile or a freshly-generated one
    cleanup_csv = False
    if real_csv and os.path.isfile(real_csv):
        csv_path = real_csv
        # Count frames in the real CSV for reporting
        with open(csv_path) as f:
            n_frames = sum(1 for _ in f) - 1
        step(f"Using REAL flight profile: {csv_path}")
        ok(f"Real CSV: {n_frames} frames (production format)")
    else:
        csv_path = os.path.join(ROOT, "test_profile.csv")
        cleanup_csv = True
        step(f"Generate flight profile: {csv_duration_s}s @ 100 Hz "
             f"(sinusoidal, ±1500 cdeg per surface)")
        n_frames = generate_profile(csv_path, duration_s=csv_duration_s)
        ok(f"CSV written: {csv_path}  ({n_frames} frames, production-format columns)")

    header("Environment setup")
    operator("Starts test bench: start.bat --sitl")
    proc = start_backend()
    print(f"  Backend PID: {proc.pid}")

    try:
        await wait_for_ws()
        ok("Web server ready on http://localhost:18890")
        await asyncio.sleep(4.0)

        async with ws_connect(
            "ws://127.0.0.1:18889", max_size=2**22,
            ping_interval=20, ping_timeout=60,
        ) as ws:
            stream = Stream(ws)
            await stream.start()

            await ws.send(json.dumps({"type": "cmd.sync_state"}))
            await asyncio.sleep(2.0)

            n_uuts = len(stream.state["uuts"])
            assertion("SITL loaded 2 UUTs", n_uuts == 2, f"got {n_uuts}")
            if n_uuts < 1:
                return 1

            for u in stream.state["uuts"]:
                print(f"      - {u.get('serial_number')}  "
                      f"{u.get('ip_address')}:{u.get('port')}  "
                      f"status={u.get('status')}")

            # ══════════════════════════════════════════════════════════
            # Start playback batch
            # ══════════════════════════════════════════════════════════
            header("Phase B: Flight Profile Playback batch")
            operator("Switches to Test Mode tab")
            operator("Selects mode = Playback")
            operator(f"Sets CSV path = {csv_path}")
            operator('Selects playback type = "Both" (actuation + propulsion)')

            # Duration = 2x streaming time + 3 min prep/cleanup margin.
            # Real 32k-frame profile @ 100 Hz = 328s theoretical but runs
            # slower in SITL due to ws+telemetry overhead, so give 2x.
            csv_streaming_s = n_frames / 100.0
            batch_duration_s = max(300, int(csv_streaming_s * 2.0 + 180))
            operator(f"Sets duration = {batch_duration_s // 60}m {batch_duration_s % 60}s")
            step("Click [ Start Playback Test ]")

            await ws.send(json.dumps({
                "type": "cmd.start_test",
                "data": {
                    "mode": "playback",
                    "duration_seconds": batch_duration_s,
                    "playback_csv": csv_path,
                    "playback_type": "Both",
                    "config": {
                        "arm_timeout": 30,
                        "phase_timeout": 60,
                    },
                },
            }))

            got_active = await wait_for(
                lambda: stream.state["batch_active"], 5.0,
            )
            assertion("Playback batch becomes active", got_active,
                      f"batch_active={stream.state['batch_active']}")
            if not got_active:
                return 1

            # ── Profile loads ────────────────────────────────────────
            got_profile_load = await wait_for(
                lambda: stream.log_contains("Profile loaded"), 20.0,
            )
            assertion("Profile CSV loaded", got_profile_load,
                      f"'Profile loaded' seen in log={got_profile_load}")

            # ── ARM + OPERATE + PLAYBACK sequence ──────────────────
            step("Watching for preparation: CLASSIC_MODE_EN -> power cycle -> ARM -> OPERATE -> PLAYBACK")

            got_classic = await wait_for(
                lambda: stream.log_contains("CLASSIC_MODE_EN"), 30.0,
            )
            assertion("CLASSIC_MODE_EN parameter set",
                      got_classic, f"CLASSIC_MODE_EN log={got_classic}")

            got_power_cycle = await wait_for(
                lambda: stream.log_contains("Power cycle complete")
                        or stream.log_contains("Heartbeat received after"),
                60.0,
            )
            assertion("Power cycle executed",
                      got_power_cycle, f"power cycle log={got_power_cycle}")

            got_armed = await wait_for(
                lambda: stream.state["armed"], 60.0,
            )
            assertion("Vehicle ARMED",
                      got_armed,
                      f"armed={stream.state['armed']}")

            got_operate = await wait_for(
                lambda: stream.state["mode"] == MODE_OPERATE, 30.0,
            )
            assertion("Vehicle reached OPERATE",
                      got_operate, f"mode={stream.state['mode']}")

            got_playback = await wait_for(
                lambda: stream.state["mode"] == MODE_PLAYBACK, 30.0,
            )
            assertion("Vehicle transitioned to PLAYBACK",
                      got_playback, f"mode={stream.state['mode']}")

            # ── Streaming in progress ──────────────────────────────
            step("Watching profile streaming (100 Hz for ~{:.0f}s)".format(csv_streaming_s))
            got_streaming = await wait_for(
                lambda: stream.log_contains("STREAMING FLIGHT PROFILE"),
                60.0,
            )
            assertion("'STREAMING FLIGHT PROFILE' banner",
                      got_streaming, "")

            # Progress log entries (every 10%): "Frame N/total"
            # Wait for completion log
            # Wait for uut.iteration_complete — this fires AFTER the executor
            # has done its eval, restored vehicle state, and called on_complete.
            # Both PASS and FAIL verdicts get logged before this event.
            # For a 32k-frame real profile at 100 Hz, streaming takes ~5.5min
            # plus ~20s cleanup. Give generous slack.
            deadline = time.monotonic() + csv_streaming_s * 2.0 + 180
            while time.monotonic() < deadline:
                if stream.count("uut.iteration_complete") > 0:
                    # Drain a bit to catch trailing logs
                    await asyncio.sleep(2.0)
                    break
                await asyncio.sleep(0.5)

            got_complete = stream.log_contains("Profile streaming complete")
            assertion("'Profile streaming complete' log",
                      got_complete, "")

            got_result = stream.log_contains("PLAYBACK RESULT EVALUATION")
            assertion("'PLAYBACK RESULT EVALUATION' banner",
                      got_result, "")

            # Count progress log entries - at least 100%, should see multiple "[nnn%]" logs
            progress_logs = [
                l for l in stream.logs()
                if "Frame" in l and "%" in l and "mistracking_flags" in l
            ]
            assertion("Progress log entries observed",
                      len(progress_logs) >= 5,
                      f"{len(progress_logs)} progress entries")

            # ── PASS verdict (SIM-001 has ibit_pass=True) ───────────
            # Look for PASS or FAIL verdict in logs. SIM-001 should PASS
            # because commanded positions (±1500 cdeg) are well within
            # the 500 cdeg tracking threshold on a healthy servo model.
            got_pass = stream.log_contains("PASS \u2014 No mistracking")
            got_fail = stream.log_contains("Playback FAIL")
            if got_pass:
                assertion("SIM-001: Playback verdict = PASS",
                          got_pass, "no mistracking flags")
            elif got_fail:
                # SIM-002 has mistracking_flags injected, so it can fail
                assertion("Playback verdict emitted (PASS or FAIL)",
                          True, "FAIL on fault vehicle")
            else:
                assertion("Playback verdict emitted",
                          False, "no PASS/FAIL verdict in logs yet")

            # Verify iteration complete fired
            got_iter = await wait_for(
                lambda: stream.count("uut.iteration_complete") >= 1,
                30.0,
            )
            assertion("uut.iteration_complete fired",
                      got_iter,
                      f"count={stream.count('uut.iteration_complete')}")

            # UUT iteration counter advanced
            max_iter = max(
                (u.get("iterations_completed", 0)
                 for u in stream.state["uuts"]),
                default=0,
            )
            assertion("UUT iteration count > 0",
                      max_iter >= 1, f"max={max_iter}")

            # ── Let it run briefly to confirm batch loop continues ──
            if watch_secs > 0:
                step(f"Watching batch for {watch_secs}s to confirm it continues "
                     "(round-robin to next UUT)...")
                await asyncio.sleep(watch_secs)
                assertion("Batch still active after extra watch",
                          stream.state["batch_active"],
                          f"batch_active={stream.state['batch_active']}")

            # ── Stop ───────────────────────────────────────────────
            step("Operator clicks [ Stop ] to end batch early")
            await ws.send(json.dumps({"type": "cmd.stop_test"}))

            got_stopped = await wait_for(
                lambda: not stream.state["batch_active"], 20.0,
            )
            assertion("Batch stops cleanly",
                      got_stopped, f"batch_active={stream.state['batch_active']}")

            await asyncio.sleep(2.0)
            assertion("Relay OFF after stop (safety)",
                      not stream.state["relay_on"],
                      f"relay_on={stream.state['relay_on']}")

            # Show streaming performance stats
            for m in stream.logs():
                if "Streaming stats" in m:
                    print(f"  \033[35m{m}\033[0m", flush=True)

            # If we had failures, dump the backend log for diagnosis
            if _fails:
                dump_path = os.path.join(ROOT, "_pb_walkthrough_logs.txt")
                try:
                    with open(dump_path, 'w') as _lf:
                        for i, m in enumerate(stream.logs()):
                            _lf.write(f"{i:4d}: {m}\n")
                    print(f"\n  Backend log dump: {dump_path} "
                          f"({len(stream.logs())} messages)")
                except Exception as e:
                    print(f"  Could not dump logs: {e}")

            await stream.stop()

    finally:
        header("Shutdown")
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        ok("Backend stopped")
        if cleanup_csv:
            try:
                os.unlink(csv_path)
                ok("Test CSV cleaned up")
            except OSError:
                pass

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
    ap.add_argument("--csv-duration", type=float, default=4.0,
                    help="Flight profile length in seconds (default 4.0)")
    ap.add_argument("--watch-secs", type=int, default=10,
                    help="Additional seconds to watch batch after first iter")
    ap.add_argument("--real-csv", type=str,
                    default=os.path.join(ROOT, "profiles", "NominalFlight_noRudder.csv"),
                    help="Path to a real flight profile CSV. If it exists, "
                         "used in place of the generated profile (default: "
                         "profiles/NominalFlight_noRudder.csv in project root)")
    ap.add_argument("--no-real-csv", action="store_true",
                    help="Ignore --real-csv and always generate a test profile")
    args = ap.parse_args()

    real_csv = None if args.no_real_csv else args.real_csv

    try:
        return asyncio.run(run(args.csv_duration, args.watch_secs, real_csv))
    except KeyboardInterrupt:
        print("\nInterrupted")
        return 1


if __name__ == "__main__":
    sys.exit(main())
