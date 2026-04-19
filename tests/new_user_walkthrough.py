#!/usr/bin/env python3
"""
new_user_walkthrough.py — Simulate what a new user sees when they run
start.bat --sitl and click the Start IBIT Test button.

This connects to the WebSocket exactly like the React frontend does,
sends the same commands a user's button clicks would send, and prints
a chronological narrative of what the UI displays at each moment.
"""
import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime

ROOT = '/mnt/c/Anduril/RoadRunner Flight Mode IBIT'


# ── Pretty output ────────────────────────────────────────────────────────

T0 = time.monotonic()
def ts() -> str:
    return f"[t+{time.monotonic() - T0:05.1f}s]"

def user(msg: str) -> None:
    print(f"\n{ts()} \033[36m USER: {msg}\033[0m", flush=True)

def ui(msg: str) -> None:
    print(f"{ts()} \033[32m UI:   {msg}\033[0m", flush=True)

def backend(msg: str) -> None:
    print(f"{ts()} \033[33m BACKEND: {msg}\033[0m", flush=True)

def header(msg: str) -> None:
    print(f"\n{'='*70}\n  {msg}\n{'='*70}", flush=True)


# ── Mode/substate name tables (match frontend) ──────────────────────────

MODE_NAMES = {
    0: "OFF", 1: "IBIT", 2: "OPERATE", 3: "MANUAL",
    4: "PLAYBACK", 5: "TRIM", 6: "POS_CHECK", 7: "TERMINAL",
}


# ── Track UI state like the React reducer does ──────────────────────────

class UIState:
    def __init__(self):
        self.link = "OFFLINE"
        self.armed = False
        self.mode = 0
        self.regime = 0
        self.relay_on = False
        self.ibit_substate = "IDLE"
        self.actuator_data = {}
        self.batch_elapsed = 0.0
        self.batch_remaining = 0.0
        self.batch_active = False
        self.uuts = []
        self.last_ui_render_sig = None

    def render_sig(self) -> str:
        """Signature of the visible UI state."""
        act_keys = sorted(k for k, v in self.actuator_data.items()
                          if isinstance(v, (int, float)) and v != 0)[:3]
        uut_iters = [u.get("iterations_completed", 0) for u in self.uuts]
        return (
            f"{self.link}|armed={self.armed}|mode={MODE_NAMES.get(self.mode, '?')}|"
            f"ibit={self.ibit_substate}|relay={self.relay_on}|"
            f"batch={self.batch_active}|elapsed={int(self.batch_elapsed)}|"
            f"actuators={len(act_keys)}|iter={uut_iters}"
        )

    def handle_event(self, msg: dict) -> bool:
        """Update state from WS message. Return True if UI needs re-render."""
        t = msg.get("type", "")
        d = msg.get("data", {}) or {}

        if t == "state.sync":
            self.uuts = d.get("uuts", [])
            batch = d.get("batch", {})
            self.batch_active = batch.get("active", False)
            self.batch_elapsed = batch.get("elapsed_seconds", 0)
            self.batch_remaining = batch.get("remaining_seconds", 0)
            vehicle = d.get("vehicle", {})
            self.link = "CONNECTED" if vehicle.get("connection_healthy") else "OFFLINE"
            self.armed = vehicle.get("armed", False)
            self.mode = vehicle.get("mode", 0)
            self.regime = vehicle.get("regime", 0)
            self.relay_on = vehicle.get("relay_on", False)
            ibit = d.get("ibit", {})
            self.ibit_substate = ibit.get("substate", "IDLE") or "IDLE"
            self.actuator_data = d.get("actuator", {}) or {}
            return True

        elif t == "connection.health":
            self.link = "CONNECTED" if d.get("healthy") else "OFFLINE"
            return True

        elif t == "telemetry.vehicle_status":
            self.armed = d.get("armed", self.armed)
            self.mode = d.get("mode", self.mode)
            self.regime = d.get("regime", self.regime)
            return True

        elif t == "telemetry.actuator":
            self.actuator_data = d
            return True

        elif t == "ibit.state":
            self.ibit_substate = d.get("substate", self.ibit_substate)
            return True

        elif t == "daq.relay":
            self.relay_on = d.get("on", self.relay_on)
            return True

        elif t == "batch.status":
            self.batch_active = d.get("active", False)
            self.batch_elapsed = d.get("elapsed_seconds", 0)
            self.batch_remaining = d.get("remaining_seconds", 0)
            return True

        elif t == "uut.update":
            self.uuts = d.get("uuts", self.uuts)
            return True

        return False

    def render(self) -> None:
        sig = self.render_sig()
        if sig == self.last_ui_render_sig:
            return
        self.last_ui_render_sig = sig

        # Timer
        mm_e = int(self.batch_elapsed) // 60
        ss_e = int(self.batch_elapsed) % 60
        mm_r = int(self.batch_remaining) // 60
        ss_r = int(self.batch_remaining) % 60

        # Actuator feedback (first 2 surfaces)
        feedback_items = [
            (k, v) for k, v in self.actuator_data.items()
            if k.endswith("_feedback_cdeg") and isinstance(v, (int, float))
        ]
        if feedback_items:
            act_str = ", ".join(
                f"{k.replace('_feedback_cdeg', '')}={int(v)}cdeg"
                for k, v in feedback_items[:2]
            )
        else:
            act_str = "---"

        # UUT status
        uut_str = ", ".join(
            f"{u.get('serial_number', '?')}:{u.get('status', '?')}"
            f"({u.get('iterations_completed', 0)})"
            for u in self.uuts
        ) if self.uuts else "no UUTs"

        ui(
            f"Link={self.link} "
            f"Armed={'YES' if self.armed else 'SAFE'} "
            f"Mode={MODE_NAMES.get(self.mode, '?')} "
            f"Test={self.ibit_substate} "
            f"Relay={'ON' if self.relay_on else 'OFF'} "
            f"Timer={mm_e:02d}:{ss_e:02d}/{mm_r:02d}:{ss_r:02d} "
            f"Act=[{act_str}] "
            f"UUTs=[{uut_str}]"
        )


# ── Main walkthrough ───────────────────────────────────────────────────

async def walkthrough():
    header("NEW USER WALKTHROUGH: Roadrunner Web GUI with SITL")

    # ── Step 1: User double-clicks start.bat --sitl ────────────────
    user("Double-clicks start.bat --sitl on the desktop")
    backend("Python server starts, binds ws://0.0.0.0:18889 and http://0.0.0.0:18890")
    backend("SITL launcher thread kicks off — creating RR-SIM-001 (PASS) and RR-SIM-002 (FAIL)")

    proc = subprocess.Popen(
        [sys.executable, '-B', os.path.join(ROOT, 'ws_server.py'), '--sitl'],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    # ── Step 2: Wait for server ready ──────────────────────────────
    from websockets.asyncio.client import connect as ws_connect

    for _ in range(20):
        try:
            async with ws_connect('ws://127.0.0.1:18889', open_timeout=1):
                break
        except Exception:
            await asyncio.sleep(0.5)
    else:
        print("ERROR: server did not start")
        proc.kill()
        return

    backend("WebSocket server ready, browser opens http://localhost:18890")

    # Give SITL thread time to fully init
    await asyncio.sleep(3)

    state = UIState()

    async with ws_connect('ws://127.0.0.1:18889', max_size=2**22, ping_interval=None) as ws:
        user("Browser loads the React app")

        # Frontend sends cmd.sync_state on connect
        await ws.send(json.dumps({"type": "cmd.sync_state"}))

        # ── Step 3: Collect initial sync + welcome log ─────────────
        deadline = time.monotonic() + 3.0
        got_sync = False
        welcome_log = None
        while time.monotonic() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=0.5)
                msg = json.loads(raw)
                if msg.get("type") == "test.log":
                    welcome_log = msg.get("data", {}).get("message")
                state.handle_event(msg)
                if msg.get("type") == "state.sync":
                    got_sync = True
            except asyncio.TimeoutError:
                if got_sync:
                    break

        ui("App loaded — initial state synced from backend")
        state.render()
        if welcome_log:
            ui(f"Log panel shows: \"{welcome_log}\"")
        else:
            ui("Log panel: (no welcome message yet)")

        # ── Step 4: User sees the SITL UUTs in the table ───────────
        await asyncio.sleep(0.5)
        if state.uuts:
            user(f"Sees {len(state.uuts)} SITL vehicles in the UUT table:")
            for u in state.uuts:
                print(f"        • {u.get('serial_number')}  "
                      f"IP={u.get('ip_address')}  Port={u.get('port')}  "
                      f"Status={u.get('status')}")
        else:
            user("Sees empty UUT table (waiting for SITL to finish loading)")
            # Wait for uut.update
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and not state.uuts:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=0.5)
                    state.handle_event(json.loads(raw))
                except asyncio.TimeoutError:
                    continue
            if state.uuts:
                ui(f"SITL ready — {len(state.uuts)} vehicles now visible")

        # ── Step 5: User clicks Start IBIT Test ────────────────────
        await asyncio.sleep(1.0)
        header("USER CLICKS: [ Start IBIT Test ]")
        user("Clicks the big green 'Start IBIT Test' button")

        await ws.send(json.dumps({
            "type": "cmd.start_test",
            "data": {
                "mode": "ibit",
                "duration_seconds": 180,
                "config": {
                    "ibit_timeout": 120,
                    "phase_timeout": 60,
                    "arm_timeout": 30,
                },
            },
        }))

        # ── Step 6: Watch the UI react in real time ────────────────
        ui("Start button dims, Stop button enables")
        ui("Watching the UI react to backend events...")
        print()

        # Collect events and re-render UI whenever state changes
        event_counts = defaultdict(int)
        complete_count = 0
        deadline = time.monotonic() + 90.0  # 90s for full IBIT cycle

        phase_milestones = {
            "CONNECTED_LINK": False,
            "ARMED": False,
            "OPERATE_MODE": False,
            "PLAYBACK_MODE": False,
            "IBIT_MODE": False,
            "SERVO_FEEDBACK": False,
            "IBIT_COMPLETE": False,
            "ITERATION_UPDATED": False,
        }

        while time.monotonic() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                msg = json.loads(raw)
                event_counts[msg.get("type", "?")] += 1

                # Show backend log messages (filtered)
                if msg.get("type") == "test.log":
                    m = msg.get("data", {}).get("message", "").strip()
                    if m and len(m) < 120 and not m.startswith(("    ", "  ✓", "    ✓")):
                        # Show interesting log entries
                        interesting = any(x in m for x in [
                            "BATCH START", "Connected to", "ARMED", "OPERATE",
                            "PLAYBACK", "IBIT", "MISTRACK", "PASS", "FAIL",
                            "DISARM", "Complete", "Error", "cooldown",
                        ])
                        if interesting and "Connected to Roadrunner" not in m:
                            backend(m[:100])

                if state.handle_event(msg):
                    state.render()

                    # Mark milestones
                    if not phase_milestones["CONNECTED_LINK"] and state.link == "CONNECTED":
                        phase_milestones["CONNECTED_LINK"] = True
                        print(f"{ts()} \033[35m ✓ MILESTONE: Link = CONNECTED (Bug 1 fix visible)\033[0m", flush=True)
                    if not phase_milestones["ARMED"] and state.armed:
                        phase_milestones["ARMED"] = True
                        print(f"{ts()} \033[35m ✓ MILESTONE: Vehicle ARMED (Bug 2 fix visible)\033[0m", flush=True)
                    if not phase_milestones["OPERATE_MODE"] and state.mode == 2:
                        phase_milestones["OPERATE_MODE"] = True
                        print(f"{ts()} \033[35m ✓ MILESTONE: Mode = OPERATE\033[0m", flush=True)
                    if not phase_milestones["PLAYBACK_MODE"] and state.mode == 4:
                        phase_milestones["PLAYBACK_MODE"] = True
                        print(f"{ts()} \033[35m ✓ MILESTONE: Mode = PLAYBACK (firmware requires this before IBIT)\033[0m", flush=True)
                    if not phase_milestones["IBIT_MODE"] and state.mode == 1:
                        phase_milestones["IBIT_MODE"] = True
                        print(f"{ts()} \033[35m ✓ MILESTONE: Mode = IBIT — actuator sweep in progress\033[0m", flush=True)
                    if not phase_milestones["SERVO_FEEDBACK"]:
                        has_nonzero = any(
                            isinstance(v, (int, float)) and abs(v) > 100
                            for k, v in state.actuator_data.items()
                            if k.endswith("_feedback_cdeg")
                        )
                        if has_nonzero:
                            phase_milestones["SERVO_FEEDBACK"] = True
                            print(f"{ts()} \033[35m ✓ MILESTONE: Actuator Feedback showing real positions (Bug 4 fix visible)\033[0m", flush=True)
                    if not phase_milestones["ITERATION_UPDATED"]:
                        max_iter = max((u.get("iterations_completed", 0) for u in state.uuts), default=0)
                        if max_iter > 0:
                            phase_milestones["ITERATION_UPDATED"] = True
                            print(f"{ts()} \033[35m ✓ MILESTONE: Iterations column updated to {max_iter} (Bug 7 fix visible)\033[0m", flush=True)

                if msg.get("type") == "test.complete":
                    complete_count += 1
                    success = msg.get("data", {}).get("success")
                    message = msg.get("data", {}).get("message", "")
                    print(f"{ts()} \033[35m ✓ TEST.COMPLETE: success={success}, msg='{message}'\033[0m", flush=True)
                    if not phase_milestones["IBIT_COMPLETE"]:
                        phase_milestones["IBIT_COMPLETE"] = True
                    if complete_count >= 2:
                        # Drain a bit more for final state
                        drain_end = time.monotonic() + 3.0
                        while time.monotonic() < drain_end:
                            try:
                                raw = await asyncio.wait_for(ws.recv(), timeout=0.5)
                                if state.handle_event(json.loads(raw)):
                                    state.render()
                            except asyncio.TimeoutError:
                                continue
                        break

            except asyncio.TimeoutError:
                continue

        # ── Step 7: User clicks Stop ───────────────────────────────
        await asyncio.sleep(1)
        user("Clicks 'Stop' button (test cycle complete)")
        await ws.send(json.dumps({"type": "cmd.stop_test"}))
        await asyncio.sleep(2)

        # ── Step 8: Summary ────────────────────────────────────────
        header("WALKTHROUGH COMPLETE")

        print("\n  Event counts during the walkthrough:")
        for t, n in sorted(event_counts.items(), key=lambda x: -x[1]):
            print(f"    {t:35s} {n:4d}")

        print("\n  Bug-fix milestones observed in the live UI:")
        labels = {
            "CONNECTED_LINK":    "Bug 1: Link OFFLINE → CONNECTED",
            "ARMED":             "Bug 2: Armed SAFE → ARMED",
            "OPERATE_MODE":      "        Mode → OPERATE",
            "PLAYBACK_MODE":     "        Mode → PLAYBACK",
            "IBIT_MODE":         "Bug 3: Mode → IBIT + substates advance",
            "SERVO_FEEDBACK":    "Bug 4: Actuator Feedback shows real positions",
            "ITERATION_UPDATED": "Bug 7: Iterations column > 0",
            "IBIT_COMPLETE":     "        test.complete received for UUTs",
        }
        for k, label in labels.items():
            mark = "+" if phase_milestones[k] else "X"
            color = "\033[32m" if phase_milestones[k] else "\033[31m"
            print(f"    {color}[{mark}]\033[0m  {label}")

        # Bug 5 = timer moved from 0
        bug5 = state.batch_elapsed > 0
        b5 = "\033[32m[+]\033[0m" if bug5 else "\033[31m[X]\033[0m"
        print(f"    {b5}  Bug 5: Elapsed timer moved past 00:00  (final={int(state.batch_elapsed)}s)")

        # Bug 6 = welcome log
        bug6 = welcome_log is not None and "Connected to Roadrunner" in welcome_log
        b6 = "\033[32m[+]\033[0m" if bug6 else "\033[31m[X]\033[0m"
        seen = "seen" if bug6 else "missed"
        print(f"    {b6}  Bug 6: Welcome log on connect  ({seen})")

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


if __name__ == "__main__":
    try:
        asyncio.run(walkthrough())
    except KeyboardInterrupt:
        print("\nInterrupted")
        sys.exit(1)
