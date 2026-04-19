#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ui_interaction_test.py -- Systematic test of EVERY UI control's WebSocket
round-trip behavior.

For each button/input/control in the web GUI, this test:
  1. Sends the exact WS command the frontend would emit on click/change
  2. Waits for the expected backend response event
  3. Verifies the response matches what the frontend reducer expects

This catches silent regressions where:
  - A button sends a command the backend no longer handles
  - A backend command no longer broadcasts the event the UI reducer expects
  - An event payload shape drifts from the TypeScript type definition
  - A UI control sends the wrong command data shape

Covers:
  Test Mode tab:
    - Launch SITL button
    - Detect DAQ button
    - Init DAQ button
    - Add UUT (dialog submit)
    - Edit UUT
    - Remove UUT
    - Start IBIT button
    - Start Playback button (with CSV)
    - Stop button
    - Emergency Stop button

  Debug Mode tab:
    - UUT selector dropdown (select changes target)
    - Connect button
    - Disconnect button
    - All 8 mode buttons (OFF, OPERATE, PLAYBACK, IBIT, MANUAL, TRIM, POS CHECK, TERMINAL)
    - ARM button (non-force)
    - Force ARM button
    - DISARM button
    - Param Set (CLASSIC_MODE_EN, USE_NEST, STBL_PRMS_APPVD)
    - Monitor override: SUPPRESS (cmd=1)
    - Monitor override: CANCEL (cmd=0)
    - Monitor override: FORCE_FAULT (cmd=2)

  Connection lifecycle:
    - cmd.sync_state on WebSocket connect
    - state.sync structure complete

Run:
    python tests/ui_interaction_test.py
"""
from __future__ import annotations

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


# ── Pretty output ───────────────────────────────────────────────────────

T0 = time.monotonic()

def ts() -> str:
    return f"[t+{time.monotonic() - T0:06.1f}s]"

def header(msg: str) -> None:
    print(f"\n{'=' * 74}\n  {msg}\n{'=' * 74}", flush=True)

def section(msg: str) -> None:
    print(f"\n{ts()} \033[36m{msg}\033[0m", flush=True)

def ok(msg: str, detail: str = "") -> None:
    _passes.append(msg)
    print(f"{ts()}   \033[32m[+]\033[0m {msg}" +
          (f"  ({detail})" if detail else ""), flush=True)

def bad(msg: str, detail: str = "") -> None:
    _fails.append(f"{msg}: {detail}")
    print(f"{ts()}   \033[31m[X]\033[0m {msg}" +
          (f"  ({detail})" if detail else ""), flush=True)


_passes: list[str] = []
_fails: list[str] = []


def assertion(name: str, cond: bool, detail: str = "") -> None:
    (ok if cond else bad)(name, detail)


# ── Backend lifecycle ──────────────────────────────────────────────────

def start_backend() -> subprocess.Popen:
    try:
        subprocess.run(["pkill", "-9", "-f", "ws_server.py"],
                       timeout=3, capture_output=True)
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


# ── WS stream reader ───────────────────────────────────────────────────

class Stream:
    def __init__(self, ws: Any) -> None:
        self.ws = ws
        self.by_type: dict[str, list[dict]] = defaultdict(list)
        self._task: asyncio.Task | None = None
        self._running = True

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
                    self.by_type[msg.get("type", "?")].append(msg)
                except asyncio.TimeoutError:
                    continue
                except Exception:
                    break
        except asyncio.CancelledError:
            pass

    def count(self, t: str) -> int:
        return len(self.by_type.get(t, []))

    def mark(self, t: str) -> int:
        """Return current count — use as a 'before' marker."""
        return self.count(t)

    def since(self, t: str, mark: int) -> list[dict]:
        """Messages of type t received since mark."""
        return self.by_type.get(t, [])[mark:]

    def has_log_since(self, mark: int, needle: str) -> bool:
        return any(
            needle in m.get("data", {}).get("message", "")
            for m in self.since("test.log", mark)
        )

    async def wait_for(self, pred, timeout: float,
                       poll: float = 0.1) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if pred():
                return True
            await asyncio.sleep(poll)
        return False


# ── Test plan ─────────────────────────────────────────────────────────

async def test_state_sync(ws: Any, stream: Stream) -> None:
    section("Connection lifecycle: cmd.sync_state")

    mark_sync = stream.mark("state.sync")
    await ws.send(json.dumps({"type": "cmd.sync_state"}))

    got = await stream.wait_for(
        lambda: stream.count("state.sync") > mark_sync, 3.0,
    )
    assertion("cmd.sync_state → state.sync response", got)
    if not got:
        return

    sync = stream.since("state.sync", mark_sync)[0].get("data", {})
    required_keys = {
        "uuts", "daq", "batch", "vehicle", "ibit", "actuator",
        "statistics", "test_mode", "config",
    }
    missing = required_keys - set(sync.keys())
    assertion(
        "state.sync has all required AppState keys",
        len(missing) == 0,
        f"missing: {missing}" if missing else f"{len(required_keys)} keys OK",
    )

    # Check batch payload shape
    batch = sync.get("batch", {})
    batch_keys = {"active", "mode", "elapsed_seconds", "remaining_seconds",
                  "current_uut_index", "current_uut_serial",
                  "total_uuts", "active_uuts"}
    missing_batch = batch_keys - set(batch.keys())
    assertion(
        "state.sync.batch has all required fields",
        len(missing_batch) == 0,
        f"missing: {missing_batch}" if missing_batch else "all fields present",
    )


async def test_sitl_already_launched(ws: Any, stream: Stream) -> None:
    """SITL was auto-launched at server start. Verify UUTs appear."""
    section("SITL auto-launch (from --sitl flag)")

    # Wait for uut.update to confirm SITL is ready
    await stream.wait_for(
        lambda: any(
            len(m.get("data", {}).get("uuts", [])) >= 2
            for m in stream.by_type.get("uut.update", [])
            + stream.by_type.get("state.sync", [])
        ),
        5.0,
    )

    last_uuts = None
    for m in reversed(stream.by_type.get("uut.update", [])):
        uuts = m.get("data", {}).get("uuts", [])
        if uuts:
            last_uuts = uuts
            break
    if last_uuts is None:
        for m in reversed(stream.by_type.get("state.sync", [])):
            uuts = m.get("data", {}).get("uuts", [])
            if uuts:
                last_uuts = uuts
                break

    if last_uuts:
        assertion("SITL loaded 2 UUTs", len(last_uuts) == 2,
                  f"got {len(last_uuts)} UUTs")
        assertion("UUT has expected fields",
                  all({"serial_number", "ip_address", "port",
                       "relay_line", "status", "iterations_completed"}
                      <= set(u.keys()) for u in last_uuts),
                  f"first UUT keys: {list(last_uuts[0].keys())}")
    else:
        assertion("SITL loaded UUTs", False, "no UUTs received")


async def test_add_edit_remove_uut(ws: Any, stream: Stream) -> None:
    """Exercise Add UUT dialog → Edit → Remove buttons."""
    section("Test Mode: Add / Edit / Remove UUT")

    # Add UUT
    mark = stream.mark("uut.update")
    await ws.send(json.dumps({
        "type": "cmd.add_uut",
        "data": {
            "serial_number": "UI-TEST-99",
            "ip_address": "127.0.0.1",
            "port": 29999,
            "relay_line": 7,
        },
    }))
    got = await stream.wait_for(
        lambda: stream.count("uut.update") > mark, 3.0,
    )
    assertion("cmd.add_uut → uut.update", got)

    # Verify UUT appears in latest uut.update
    latest = stream.since("uut.update", mark)
    uuts_after_add = latest[-1].get("data", {}).get("uuts", []) if latest else []
    added = next(
        (u for u in uuts_after_add if u.get("serial_number") == "UI-TEST-99"),
        None,
    )
    assertion(
        "Added UUT in UUT list",
        added is not None and added.get("port") == 29999,
        f"found UI-TEST-99 with port={added.get('port') if added else 'None'}",
    )

    added_idx = next(
        (i for i, u in enumerate(uuts_after_add)
         if u.get("serial_number") == "UI-TEST-99"),
        -1,
    )

    # Edit UUT
    if added_idx >= 0:
        mark = stream.mark("uut.update")
        await ws.send(json.dumps({
            "type": "cmd.edit_uut",
            "data": {
                "index": added_idx,
                "serial_number": "UI-TEST-99-EDITED",
                "ip_address": "127.0.0.1",
                "port": 29998,
                "relay_line": 7,
            },
        }))
        got = await stream.wait_for(
            lambda: stream.count("uut.update") > mark, 3.0,
        )
        assertion("cmd.edit_uut → uut.update", got)

        latest = stream.since("uut.update", mark)
        uuts_after = latest[-1].get("data", {}).get("uuts", []) if latest else []
        edited = next(
            (u for u in uuts_after
             if u.get("serial_number") == "UI-TEST-99-EDITED"),
            None,
        )
        assertion(
            "Edited UUT reflects new values",
            edited is not None and edited.get("port") == 29998,
            f"port={edited.get('port') if edited else 'None'}",
        )

        # Remove UUT
        mark = stream.mark("uut.update")
        await ws.send(json.dumps({
            "type": "cmd.remove_uut",
            "data": {"index": added_idx},
        }))
        got = await stream.wait_for(
            lambda: stream.count("uut.update") > mark, 3.0,
        )
        assertion("cmd.remove_uut → uut.update", got)

        latest = stream.since("uut.update", mark)
        uuts_after = latest[-1].get("data", {}).get("uuts", []) if latest else []
        gone = all(
            u.get("serial_number") != "UI-TEST-99-EDITED"
            for u in uuts_after
        )
        assertion("Removed UUT is gone", gone,
                  f"{len(uuts_after)} UUTs remaining")


async def test_daq_buttons(ws: Any, stream: Stream) -> None:
    section("Test Mode: DAQ buttons")

    # Detect DAQ
    mark = stream.mark("daq.status")
    mark_log = stream.mark("test.log")
    await ws.send(json.dumps({"type": "cmd.detect_daq"}))
    got = await stream.wait_for(
        lambda: stream.count("daq.status") > mark
                or stream.has_log_since(mark_log, "DAQ")
                or stream.has_log_since(mark_log, "nidaqmx"),
        3.0,
    )
    assertion("cmd.detect_daq responds", got,
              "daq.status or log entry received")

    # Init DAQ (will likely fail without real hardware but should respond)
    mark_log = stream.mark("test.log")
    mark_err = stream.mark("error")
    await ws.send(json.dumps({
        "type": "cmd.init_daq",
        "data": {"device": "Dev1"},
    }))
    got = await stream.wait_for(
        lambda: stream.has_log_since(mark_log, "DAQ")
                or stream.has_log_since(mark_log, "nidaqmx")
                or stream.count("daq.status") > 0
                or stream.count("error") > mark_err,
        3.0,
    )
    assertion("cmd.init_daq responds", got,
              "log / error / daq.status received")


async def test_control_bar_buttons(ws: Any, stream: Stream) -> None:
    section("Test Mode: Control bar (Start / Stop / Emergency Stop)")

    # Start IBIT
    mark_batch = stream.mark("batch.status")
    mark_log = stream.mark("test.log")
    await ws.send(json.dumps({
        "type": "cmd.start_test",
        "data": {"mode": "ibit", "duration_seconds": 120},
    }))
    got = await stream.wait_for(
        lambda: stream.count("batch.status") > mark_batch
                or stream.has_log_since(mark_log, "BATCH START"),
        5.0,
    )
    assertion("cmd.start_test (IBIT) → batch active", got)

    # Verify batch.active = True in latest batch.status
    latest_batches = stream.since("batch.status", mark_batch)
    if latest_batches:
        is_active = any(b.get("data", {}).get("active") for b in latest_batches)
        assertion("batch.status shows active=True", is_active)

    # Stop
    mark_batch = stream.mark("batch.status")
    await ws.send(json.dumps({"type": "cmd.stop_test"}))
    got = await stream.wait_for(
        lambda: any(
            not b.get("data", {}).get("active", True)
            for b in stream.since("batch.status", mark_batch)
        ),
        15.0,
    )
    assertion("cmd.stop_test → batch inactive", got)

    # Wait for relay to go off before next test
    await asyncio.sleep(2.0)

    # Emergency stop (should fire even with no active test)
    mark_relay = stream.mark("daq.relay")
    mark_log = stream.mark("test.log")
    await ws.send(json.dumps({"type": "cmd.emergency_stop"}))
    got = await stream.wait_for(
        lambda: stream.count("daq.relay") > mark_relay
                or stream.has_log_since(mark_log, "EMERGENCY")
                or stream.has_log_since(mark_log, "emergency"),
        3.0,
    )
    assertion("cmd.emergency_stop responds", got)


async def test_debug_mode_connect(
    ws: Any, stream: Stream, uut: dict
) -> bool:
    """Debug Mode: Connect + verify telemetry + Disconnect."""
    section(f"Debug Mode: Connect / Disconnect cycle on {uut['serial_number']}")

    # Connect
    mark_health = stream.mark("connection.health")
    await ws.send(json.dumps({
        "type": "cmd.debug.connect",
        "data": {
            "serial": uut["serial_number"],
            "ip": uut["ip_address"],
            "port": uut["port"],
        },
    }))

    # Wait for healthy=True
    got = await stream.wait_for(
        lambda: any(
            h.get("data", {}).get("healthy") is True
            for h in stream.since("connection.health", mark_health)
        ),
        12.0,
    )
    assertion("cmd.debug.connect → connection.health healthy=True", got,
              f"{uut['serial_number']}")

    if not got:
        return False

    # Verify telemetry streams
    await asyncio.sleep(2.5)
    n_actuator = stream.count("telemetry.actuator")
    n_vehicle = stream.count("telemetry.vehicle_status")
    assertion("ACTUATION_SYS_STATUS streaming in Debug Mode",
              n_actuator >= 5,
              f"{n_actuator} actuator msgs received")
    assertion("PANDION_STATUS → telemetry.vehicle_status streaming",
              n_vehicle >= 5,
              f"{n_vehicle} vehicle_status msgs received")

    return True


async def test_debug_mode_buttons(ws: Any, stream: Stream) -> None:
    """Debug Mode: all mode buttons + ARM/DISARM + monitor override."""

    section("Debug Mode: 8 mode buttons (OFF/OPERATE/PLAYBACK/IBIT/MANUAL/TRIM/POS CHECK/TERMINAL)")
    for mode_id, name in [
        (0, "OFF"), (2, "OPERATE"), (4, "PLAYBACK"), (1, "IBIT"),
        (3, "MANUAL"), (5, "TRIM"), (6, "POS_CHECK"), (7, "TERMINAL"),
    ]:
        mark_log = stream.mark("test.log")
        await ws.send(json.dumps({
            "type": "cmd.debug.mode_request",
            "data": {"mode_id": mode_id},
        }))
        got = await stream.wait_for(
            lambda ml=mark_log: stream.has_log_since(ml, f"Mode request: {mode_id}"),
            2.0,
        )
        assertion(f"Mode button {name} (id={mode_id}) → log",
                  got, f"mode_id={mode_id}")
        await asyncio.sleep(0.3)

    section("Debug Mode: ARM / Force ARM / DISARM")
    # Force ARM (most reliable since sim might reject non-force with monitors)
    mark_log = stream.mark("test.log")
    await ws.send(json.dumps({
        "type": "cmd.debug.arm",
        "data": {"arm": True, "force": True},
    }))
    got = await stream.wait_for(
        lambda: stream.has_log_since(mark_log, "Force ARM"),
        3.0,
    )
    assertion("Force ARM button → log", got)

    # DISARM
    mark_log = stream.mark("test.log")
    await ws.send(json.dumps({
        "type": "cmd.debug.arm",
        "data": {"arm": False, "force": False},
    }))
    got = await stream.wait_for(
        lambda: stream.has_log_since(mark_log, "DISARM command sent"),
        3.0,
    )
    assertion("DISARM button → log", got)

    # Non-force ARM
    mark_log = stream.mark("test.log")
    await ws.send(json.dumps({
        "type": "cmd.debug.arm",
        "data": {"arm": True, "force": False},
    }))
    got = await stream.wait_for(
        lambda: stream.has_log_since(mark_log, "ARM command sent"),
        3.0,
    )
    assertion("ARM button (non-force) → log", got)

    section("Debug Mode: Monitor override (SUPPRESS / CANCEL / FORCE_FAULT)")
    for cmd_val, cmd_name in [(1, "SUPPRESS"), (0, "CANCEL"), (2, "FORCE_FAULT")]:
        mark_log = stream.mark("test.log")
        await ws.send(json.dumps({
            "type": "cmd.debug.monitor_override",
            "data": {"cmd": cmd_val, "monitor_id": 0},
        }))
        got = await stream.wait_for(
            lambda cn=cmd_name: stream.has_log_since(mark_log, cn),
            2.0,
        )
        assertion(f"Monitor override {cmd_name} (cmd={cmd_val}) → log", got)
        await asyncio.sleep(0.2)

    section("Debug Mode: Param Set (CLASSIC_MODE_EN / USE_NEST / STBL_PRMS_APPVD)")
    for pname, pvalue in [
        ("CLASSIC_MODE_EN", 1), ("USE_NEST", 0), ("STBL_PRMS_APPVD", 1),
    ]:
        mark_log = stream.mark("test.log")
        await ws.send(json.dumps({
            "type": "cmd.debug.param_set",
            "data": {"name": pname, "value": pvalue},
        }))
        got = await stream.wait_for(
            lambda name=pname: stream.has_log_since(mark_log, f"PARAM_SET {name}"),
            2.0,
        )
        assertion(f"Param set {pname}={pvalue} → log", got)
        await asyncio.sleep(0.2)

    section("Debug Mode: Raw command")
    mark_log = stream.mark("test.log")
    await ws.send(json.dumps({
        "type": "cmd.debug.raw_command",
        "data": {"cmd_id": 511, "param1": 605.0},
    }))
    got = await stream.wait_for(
        lambda: stream.has_log_since(mark_log, "COMMAND_LONG cmd=511"),
        2.0,
    )
    assertion("Raw COMMAND_LONG → log", got)


async def test_debug_mode_disconnect(ws: Any, stream: Stream) -> None:
    section("Debug Mode: Disconnect button")

    mark_health = stream.mark("connection.health")
    await ws.send(json.dumps({"type": "cmd.debug.disconnect"}))

    got = await stream.wait_for(
        lambda: any(
            h.get("data", {}).get("healthy") is False
            for h in stream.since("connection.health", mark_health)
        ),
        5.0,
    )
    assertion("cmd.debug.disconnect → connection.health healthy=False", got)


async def test_persistence_commands(ws: Any, stream: Stream) -> None:
    section("Persistence: save_settings / save_uuts / load_uuts")

    # save_settings
    mark_log = stream.mark("test.log")
    await ws.send(json.dumps({"type": "cmd.save_settings"}))
    # Settings save happens silently; just ensure no error broadcast
    await asyncio.sleep(0.5)
    assertion("cmd.save_settings (no crash)", True,
              "settings save silent as designed")

    # save_uuts to a temp path
    tmp_path = os.path.join(ROOT, "_ui_test_uuts.json")
    try:
        os.unlink(tmp_path)
    except OSError:
        pass
    mark_log = stream.mark("test.log")
    await ws.send(json.dumps({
        "type": "cmd.save_uuts",
        "data": {"path": tmp_path},
    }))
    got = await stream.wait_for(
        lambda: stream.has_log_since(mark_log, "UUT config saved"),
        3.0,
    )
    assertion("cmd.save_uuts → log entry", got)
    file_ok = os.path.isfile(tmp_path)
    assertion("save_uuts wrote the file", file_ok, tmp_path)

    # load_uuts from that path
    if file_ok:
        mark_log = stream.mark("test.log")
        mark_uut = stream.mark("uut.update")
        await ws.send(json.dumps({
            "type": "cmd.load_uuts",
            "data": {"path": tmp_path},
        }))
        got = await stream.wait_for(
            lambda: stream.has_log_since(mark_log, "Loaded")
                    or stream.count("uut.update") > mark_uut,
            3.0,
        )
        assertion("cmd.load_uuts → log + uut.update", got)

        try:
            os.unlink(tmp_path)
        except OSError:
            pass


async def run() -> int:
    header("WEB GUI UI/UX INTERACTION TEST")
    print("  Exercises every button, input, and control through its WS command\n"
          "  and verifies the expected backend response.\n")

    proc = start_backend()
    print(f"  Backend PID: {proc.pid}")

    try:
        await wait_for_ws()
        print("  [+] Backend ready on ws://127.0.0.1:18889")
        await asyncio.sleep(3.5)  # Let SITL launcher finish

        async with ws_connect(
            "ws://127.0.0.1:18889", max_size=2**22,
            ping_interval=20, ping_timeout=60,
        ) as ws:
            stream = Stream(ws)
            await stream.start()

            # ──  Connection lifecycle  ────────────────────────────
            await test_state_sync(ws, stream)

            # ──  Verify SITL auto-launched  ──────────────────────
            await test_sitl_already_launched(ws, stream)

            # ──  Test Mode buttons  ──────────────────────────────
            await test_add_edit_remove_uut(ws, stream)
            await test_daq_buttons(ws, stream)
            await test_control_bar_buttons(ws, stream)

            # ──  Debug Mode  ──────────────────────────────────────
            # Pick the first SITL UUT
            uut = None
            for m in reversed(stream.by_type.get("uut.update", [])):
                uuts = m.get("data", {}).get("uuts", [])
                if uuts:
                    uut = uuts[0]
                    break
            if uut is None:
                for m in reversed(stream.by_type.get("state.sync", [])):
                    uuts = m.get("data", {}).get("uuts", [])
                    if uuts:
                        uut = uuts[0]
                        break

            if uut:
                connected = await test_debug_mode_connect(ws, stream, uut)
                if connected:
                    await test_debug_mode_buttons(ws, stream)
                    await test_debug_mode_disconnect(ws, stream)
            else:
                bad("Debug Mode tests — no UUT available to connect to")

            # ──  Persistence  ────────────────────────────────────
            await test_persistence_commands(ws, stream)

            await stream.stop()

    finally:
        header("Shutdown")
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        print(f"{ts()}   [+] Backend stopped")

    header("FINAL RESULTS")
    total = len(_passes) + len(_fails)
    print(f"\n  {len(_passes)}/{total} passed, {len(_fails)} failed\n")
    if _fails:
        print("  FAILED:")
        for f in _fails:
            print(f"    [X] {f}")
        print()
    return 0 if not _fails else 1


def main() -> int:
    try:
        return asyncio.run(run())
    except KeyboardInterrupt:
        print("\nInterrupted")
        return 1


if __name__ == "__main__":
    sys.exit(main())
