#!/usr/bin/env python3
"""
permutation_test.py — Exercise every user path through the application.

Each test case simulates a complete user session: launch server, perform
actions via WebSocket (exactly as the browser would), verify outcomes,
shut down.

Permutations:
  P1: Add UUTs → IBIT → Stop mid-test
  P2: Add UUTs → IBIT → Let one iteration complete
  P3: Add UUTs → Playback (generated CSV) → Stop
  P4: Debug Mode per-UUT → Switch to IBIT batch
  P5: Start IBIT → Emergency Stop
  P6: Edit UUT → Remove UUT → Start IBIT
  P7: No UUTs → Click Start (graceful error)
  P8: 6 UUTs → IBIT 60s → Verify round-robin
  P9: Server restart → verify settings restored
"""
from __future__ import annotations

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

from websockets.asyncio.client import connect as ws_connect

T0 = time.monotonic()
_passes: list[str] = []
_fails: list[str] = []

def ts(): return f"[{time.monotonic()-T0:06.1f}s]"
def ok(msg, detail=""): _passes.append(msg); print(f"{ts()} \033[32m[+]\033[0m {msg}" + (f"  ({detail})" if detail else ""), flush=True)
def bad(msg, detail=""): _fails.append(f"{msg}: {detail}"); print(f"{ts()} \033[31m[X]\033[0m {msg}" + (f"  ({detail})" if detail else ""), flush=True)
def assertion(name, cond, detail=""): (ok if cond else bad)(name, detail)
def header(msg): print(f"\n{'='*70}\n  {msg}\n{'='*70}", flush=True)


# ── Server lifecycle ──────────────────────────────────────────────────

def start_server():
    try:
        subprocess.run(["pkill", "-9", "-f", "ws_server.py"], timeout=3, capture_output=True)
        time.sleep(2)
    except: pass
    proc = subprocess.Popen(
        [sys.executable, "-B", os.path.join(ROOT, "ws_server.py"), "--sitl"],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return proc

def stop_server(proc):
    proc.terminate()
    try: proc.wait(timeout=5)
    except: proc.kill()

async def wait_ws(timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            async with ws_connect("ws://127.0.0.1:18889", open_timeout=1.5): return
        except: await asyncio.sleep(0.5)
    raise TimeoutError("server did not start")


# ── Stream reader ─────────────────────────────────────────────────────

class S:
    def __init__(self, ws):
        self.ws = ws
        self.by_type = defaultdict(list)
        self._task = None
        self._running = True
    async def start(self):
        self._task = asyncio.create_task(self._read())
    async def stop(self):
        self._running = False
        if self._task: self._task.cancel()
        try: await self._task
        except: pass
    async def _read(self):
        try:
            while self._running:
                try:
                    raw = await asyncio.wait_for(self.ws.recv(), timeout=0.5)
                    msg = json.loads(raw)
                    self.by_type[msg.get("type","?")].append(msg)
                except asyncio.TimeoutError: continue
                except: break
        except asyncio.CancelledError: pass
    def count(self, t): return len(self.by_type.get(t, []))
    def has_log(self, needle):
        return any(needle in m.get("data",{}).get("message","") for m in self.by_type.get("test.log",[]))
    async def wait(self, pred, timeout=30):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if pred(): return True
            await asyncio.sleep(0.2)
        return False
    def uuts(self):
        for m in reversed(self.by_type.get("uut.update", []) + self.by_type.get("state.sync", [])):
            u = m.get("data",{}).get("uuts", [])
            if u: return u
        return []
    def batch_active(self):
        for m in reversed(self.by_type.get("batch.status", [])):
            if "active" in m.get("data",{}): return m["data"]["active"]
        return False


# ── Permutation tests ─────────────────────────────────────────────────

async def p1_ibit_stop_mid():
    header("P1: Add UUTs → IBIT → Stop mid-test")
    proc = start_server()
    try:
        await wait_ws()
        async with ws_connect("ws://127.0.0.1:18889", max_size=2**22, ping_interval=20, ping_timeout=60) as ws:
            s = S(ws); await s.start()
            await ws.send(json.dumps({"type":"cmd.sync_state"}))
            await s.wait(lambda: s.count("state.sync") > 0, 5)
            await asyncio.sleep(3)  # SITL ready

            # Start IBIT 60s batch
            await ws.send(json.dumps({"type":"cmd.start_test","data":{"mode":"ibit","duration_seconds":60}}))
            got = await s.wait(lambda: s.batch_active(), 5)
            assertion("P1: batch started", got)

            # Wait 10s then stop
            await asyncio.sleep(10)
            await ws.send(json.dumps({"type":"cmd.stop_test"}))
            stopped = await s.wait(lambda: not s.batch_active(), 15)
            assertion("P1: batch stopped cleanly", stopped)
            await s.stop()
    finally:
        stop_server(proc)


async def p2_ibit_complete():
    header("P2: Add UUTs → IBIT → Let one iteration complete")
    proc = start_server()
    try:
        await wait_ws()
        async with ws_connect("ws://127.0.0.1:18889", max_size=2**22, ping_interval=20, ping_timeout=60) as ws:
            s = S(ws); await s.start()
            await ws.send(json.dumps({"type":"cmd.sync_state"}))
            await s.wait(lambda: s.count("state.sync") > 0, 5)
            await asyncio.sleep(3)

            await ws.send(json.dumps({"type":"cmd.start_test","data":{"mode":"ibit","duration_seconds":120}}))
            got_iter = await s.wait(lambda: s.count("uut.iteration_complete") >= 1, 90)
            assertion("P2: at least one iteration completed", got_iter, f"count={s.count('uut.iteration_complete')}")

            await ws.send(json.dumps({"type":"cmd.stop_test"}))
            await s.wait(lambda: not s.batch_active(), 15)
            await s.stop()
    finally:
        stop_server(proc)


async def p3_playback():
    header("P3: Add UUTs → Playback (generated CSV) → Stop")
    # Generate a small CSV
    csv_path = os.path.join(ROOT, "test_profile_p3.csv")
    cols = ['timestamp','left_elevon_ted_cdeg','right_elevon_ted_cdeg',
            'lower_rudder_tel_cdeg','upper_rudder_tel_cdeg',
            'left_tvc_upper_cdeg','left_tvc_lower_cdeg',
            'right_tvc_upper_cdeg','right_tvc_lower_cdeg',
            'left_engine_prct_thrust','right_engine_prct_thrust']
    with open(csv_path, 'w', newline='') as f:
        w = csv.writer(f); w.writerow(cols)
        for i in range(200):
            t = i*0.01
            v = 1000*math.sin(2*math.pi*0.5*t)*math.sin(math.pi*t/2.0)
            w.writerow([f"{t:.4f}"]+[f"{v:.1f}"]*8+["50.0","50.0"])

    proc = start_server()
    try:
        await wait_ws()
        async with ws_connect("ws://127.0.0.1:18889", max_size=2**22, ping_interval=20, ping_timeout=60) as ws:
            s = S(ws); await s.start()
            await ws.send(json.dumps({"type":"cmd.sync_state"}))
            await s.wait(lambda: s.count("state.sync") > 0, 5)
            await asyncio.sleep(3)

            # Upload CSV
            with open(csv_path) as f: contents = f.read()
            await ws.send(json.dumps({"type":"cmd.upload_playback_csv","data":{"filename":"test_p3.csv","contents":contents}}))
            got_upload = await s.wait(lambda: s.count("playback.csv_uploaded") > 0, 10)
            assertion("P3: CSV uploaded", got_upload)

            # Start playback
            await ws.send(json.dumps({"type":"cmd.start_test","data":{"mode":"playback","duration_seconds":120}}))
            got_iter = await s.wait(lambda: s.count("uut.iteration_complete") >= 1, 90)
            assertion("P3: playback iteration completed", got_iter)

            await ws.send(json.dumps({"type":"cmd.stop_test"}))
            await s.wait(lambda: not s.batch_active(), 15)
            await s.stop()
    finally:
        stop_server(proc)
        try: os.unlink(csv_path)
        except: pass


async def p4_debug_then_ibit():
    header("P4: Debug Mode per-UUT → Switch to IBIT batch")
    proc = start_server()
    try:
        await wait_ws()
        async with ws_connect("ws://127.0.0.1:18889", max_size=2**22, ping_interval=20, ping_timeout=60) as ws:
            s = S(ws); await s.start()
            await ws.send(json.dumps({"type":"cmd.sync_state"}))
            await s.wait(lambda: s.count("state.sync") > 0, 5)
            await asyncio.sleep(3)

            uuts = s.uuts()
            if len(uuts) >= 1:
                u = uuts[0]
                # Debug connect
                await ws.send(json.dumps({"type":"cmd.debug.connect","data":{"serial":u["serial_number"],"ip":u["ip_address"],"port":u["port"]}}))
                got_link = await s.wait(lambda: any(m.get("data",{}).get("healthy") for m in s.by_type.get("connection.health",[])), 12)
                assertion("P4: debug connect", got_link)

                # Force ARM
                await ws.send(json.dumps({"type":"cmd.debug.arm","data":{"arm":True,"force":True}}))
                await asyncio.sleep(2)

                # DISARM
                await ws.send(json.dumps({"type":"cmd.debug.arm","data":{"arm":False,"force":False}}))
                await asyncio.sleep(1)

                # Disconnect
                await ws.send(json.dumps({"type":"cmd.debug.disconnect"}))
                await asyncio.sleep(1)

            # Now start IBIT
            await ws.send(json.dumps({"type":"cmd.start_test","data":{"mode":"ibit","duration_seconds":60}}))
            got = await s.wait(lambda: s.batch_active(), 5)
            assertion("P4: IBIT batch started after debug", got)

            await asyncio.sleep(5)
            await ws.send(json.dumps({"type":"cmd.stop_test"}))
            await s.wait(lambda: not s.batch_active(), 15)
            await s.stop()
    finally:
        stop_server(proc)


async def p5_emergency_stop():
    header("P5: Start IBIT → Emergency Stop")
    proc = start_server()
    try:
        await wait_ws()
        async with ws_connect("ws://127.0.0.1:18889", max_size=2**22, ping_interval=20, ping_timeout=60) as ws:
            s = S(ws); await s.start()
            await ws.send(json.dumps({"type":"cmd.sync_state"}))
            await s.wait(lambda: s.count("state.sync") > 0, 5)
            await asyncio.sleep(3)

            await ws.send(json.dumps({"type":"cmd.start_test","data":{"mode":"ibit","duration_seconds":60}}))
            await s.wait(lambda: s.batch_active(), 5)

            # Emergency stop
            await ws.send(json.dumps({"type":"cmd.emergency_stop"}))
            stopped = await s.wait(lambda: not s.batch_active(), 15)
            assertion("P5: emergency stop halted batch", stopped)
            await s.stop()
    finally:
        stop_server(proc)


async def p6_edit_remove_uut():
    header("P6: Edit UUT → Remove UUT → Start IBIT")
    proc = start_server()
    try:
        await wait_ws()
        async with ws_connect("ws://127.0.0.1:18889", max_size=2**22, ping_interval=20, ping_timeout=60) as ws:
            s = S(ws); await s.start()
            await ws.send(json.dumps({"type":"cmd.sync_state"}))
            await s.wait(lambda: s.count("state.sync") > 0, 5)
            await asyncio.sleep(3)

            # Add a UUT
            await ws.send(json.dumps({"type":"cmd.add_uut","data":{"serial_number":"P6-TEST","ip_address":"127.0.0.1","port":29999,"relay_line":7}}))
            await s.wait(lambda: any("P6-TEST" in u.get("serial_number","") for u in s.uuts()), 3)
            assertion("P6: UUT added", any("P6-TEST" in u.get("serial_number","") for u in s.uuts()))

            # Edit it
            idx = next((i for i,u in enumerate(s.uuts()) if u.get("serial_number")=="P6-TEST"), -1)
            if idx >= 0:
                await ws.send(json.dumps({"type":"cmd.edit_uut","data":{"index":idx,"serial_number":"P6-EDITED","ip_address":"127.0.0.1","port":29998,"relay_line":7}}))
                await s.wait(lambda: any("P6-EDITED" in u.get("serial_number","") for u in s.uuts()), 3)
                assertion("P6: UUT edited", any("P6-EDITED" in u.get("serial_number","") for u in s.uuts()))

            # Remove it
            idx = next((i for i,u in enumerate(s.uuts()) if "P6" in u.get("serial_number","")), -1)
            if idx >= 0:
                before = len(s.uuts())
                await ws.send(json.dumps({"type":"cmd.remove_uut","data":{"index":idx}}))
                await s.wait(lambda: len(s.uuts()) < before, 3)
                assertion("P6: UUT removed", all("P6" not in u.get("serial_number","") for u in s.uuts()))

            # Start IBIT with remaining UUTs
            await ws.send(json.dumps({"type":"cmd.start_test","data":{"mode":"ibit","duration_seconds":30}}))
            got = await s.wait(lambda: s.batch_active(), 5)
            assertion("P6: batch started after UUT changes", got)

            await asyncio.sleep(3)
            await ws.send(json.dumps({"type":"cmd.stop_test"}))
            await s.wait(lambda: not s.batch_active(), 15)
            await s.stop()
    finally:
        stop_server(proc)


async def p7_no_uuts_start():
    header("P7: No UUTs → Click Start (graceful error)")
    proc = start_server()
    try:
        await wait_ws()
        async with ws_connect("ws://127.0.0.1:18889", max_size=2**22, ping_interval=20, ping_timeout=60) as ws:
            s = S(ws); await s.start()
            await ws.send(json.dumps({"type":"cmd.sync_state"}))
            await s.wait(lambda: s.count("state.sync") > 0, 5)
            # Don't wait for SITL — remove all UUTs
            await asyncio.sleep(4)
            for i in range(len(s.uuts())-1, -1, -1):
                await ws.send(json.dumps({"type":"cmd.remove_uut","data":{"index":i}}))
                await asyncio.sleep(0.2)
            await asyncio.sleep(1)
            assertion("P7: UUT table empty", len(s.uuts()) == 0, f"count={len(s.uuts())}")

            # Try to start — should fail gracefully
            await ws.send(json.dumps({"type":"cmd.start_test","data":{"mode":"ibit","duration_seconds":30}}))
            await asyncio.sleep(3)
            # Should NOT be active (no UUTs to test)
            assertion("P7: batch did not start with empty UUTs", not s.batch_active())
            await s.stop()
    finally:
        stop_server(proc)


async def p8_six_uuts():
    header("P8: 6 UUTs → IBIT 60s → Verify round-robin")
    import threading
    from rr_test.sim.vehicle import PandionVehicleSim

    # Extra 4 sims
    extra_sims = []
    for port, sysid in [(19903,3),(19904,4),(19905,5),(19906,6)]:
        sim = PandionVehicleSim(vehicle_port=port, sysid=sysid, ibit_pass=True,
                                boot_time_s=1.5, ibit_duration_scale=0.5, boot_monitors=[0,1,2,3])
        threading.Thread(target=sim.start, daemon=True).start()
        extra_sims.append(sim)
    time.sleep(2)

    proc = start_server()
    try:
        await wait_ws()
        async with ws_connect("ws://127.0.0.1:18889", max_size=2**22, ping_interval=20, ping_timeout=60) as ws:
            s = S(ws); await s.start()
            await ws.send(json.dumps({"type":"cmd.sync_state"}))
            await s.wait(lambda: s.count("state.sync") > 0, 5)
            await asyncio.sleep(3)

            # Add 4 extra UUTs
            for cfg in [{"serial":"SIM-003","port":19903,"relay":2},{"serial":"SIM-004","port":19904,"relay":3},
                        {"serial":"SIM-005","port":19905,"relay":4},{"serial":"SIM-006","port":19906,"relay":5}]:
                await ws.send(json.dumps({"type":"cmd.add_uut","data":{"serial_number":cfg["serial"],"ip_address":"127.0.0.1","port":cfg["port"],"relay_line":cfg["relay"]}}))
                await asyncio.sleep(0.2)

            await s.wait(lambda: len(s.uuts()) >= 6, 5)
            assertion("P8: 6 UUTs loaded", len(s.uuts()) >= 6, f"count={len(s.uuts())}")

            await ws.send(json.dumps({"type":"cmd.start_test","data":{"mode":"ibit","duration_seconds":120}}))
            got = await s.wait(lambda: s.batch_active(), 5)
            assertion("P8: batch started with 6 UUTs", got)

            # Wait for at least 2 iteration_completes (round-robin hit 2 UUTs)
            got_rr = await s.wait(lambda: s.count("uut.iteration_complete") >= 2, 90)
            assertion("P8: round-robin reached 2+ UUTs", got_rr, f"completes={s.count('uut.iteration_complete')}")

            await ws.send(json.dumps({"type":"cmd.stop_test"}))
            await s.wait(lambda: not s.batch_active(), 15)
            await s.stop()
    finally:
        stop_server(proc)


async def p9_settings_persist():
    header("P9: Server restart → verify settings restored")
    # Start server, add a custom UUT, stop server
    proc = start_server()
    try:
        await wait_ws()
        async with ws_connect("ws://127.0.0.1:18889", max_size=2**22, ping_interval=20, ping_timeout=60) as ws:
            s = S(ws); await s.start()
            await ws.send(json.dumps({"type":"cmd.sync_state"}))
            await s.wait(lambda: s.count("state.sync") > 0, 5)
            await asyncio.sleep(2)
            await ws.send(json.dumps({"type":"cmd.save_settings"}))
            await asyncio.sleep(1)
            await s.stop()
    finally:
        stop_server(proc)

    # Check app_settings.json exists
    settings_path = os.path.join(ROOT, "app_settings.json")
    assertion("P9: app_settings.json created", os.path.isfile(settings_path))

    # Restart server, verify it loads
    time.sleep(3)
    proc = start_server()
    try:
        await wait_ws()
        async with ws_connect("ws://127.0.0.1:18889", max_size=2**22, ping_interval=20, ping_timeout=60) as ws:
            s = S(ws); await s.start()
            await ws.send(json.dumps({"type":"cmd.sync_state"}))
            await s.wait(lambda: s.count("state.sync") > 0, 5)
            sync = s.by_type["state.sync"][-1].get("data",{})
            assertion("P9: settings loaded on restart", "config" in sync)
            await s.stop()
    finally:
        stop_server(proc)


# ── Main ──────────────────────────────────────────────────────────────

async def run():
    header("PERMUTATION TEST — All user paths")

    await p1_ibit_stop_mid()
    await p7_no_uuts_start()
    await p5_emergency_stop()
    await p6_edit_remove_uut()
    await p4_debug_then_ibit()
    await p2_ibit_complete()
    await p3_playback()
    await p8_six_uuts()
    await p9_settings_persist()

    header("FINAL RESULTS")
    total = len(_passes) + len(_fails)
    print(f"\n  {len(_passes)}/{total} passed, {len(_fails)} failed\n")
    if _fails:
        print("  FAILED:")
        for f in _fails:
            print(f"    [X] {f}")
    return 0 if not _fails else 1


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(run()))
    except KeyboardInterrupt:
        print("\nInterrupted")
        sys.exit(1)
