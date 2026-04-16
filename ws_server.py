"""
ws_server.py — WebSocket bridge between the React frontend and the Python backend.

This is a thin wrapper that:
  1. Runs an asyncio WebSocket server on port 18889
  2. Translates ExecutorCallbacks events into JSON messages (server → client)
  3. Translates JSON commands from the frontend into calls on existing code (client → server)

All domain logic remains in vehicle/, testing/, hardware/, sim/ — untouched.

Usage:
    python ws_server.py              # Start backend + WebSocket server
    python ws_server.py --sitl       # Auto-launch SITL on startup
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
import threading
import argparse
from datetime import datetime
from typing import Any, Optional, Set

import websockets
from websockets.asyncio.server import serve, ServerConnection
from websockets.http11 import Response

# ---------------------------------------------------------------------------
# Ensure project root is on sys.path so we can import vehicle/, testing/, etc.
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from vehicle.connection import UUT
from vehicle.constants import TestMode, UUTStatus, AlertSeverity
from hardware.daq import SimpleDAQController
from testing import UUTTestExecutor, PlaybackTestExecutor, BatchWatchdog
from testing.callbacks import ExecutorCallbacks

_log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)

WS_PORT = 18889
HTTP_PORT = 18890  # Static file server for the built React frontend

# ── Static file MIME types ────────────────────────────────────────────────────
_MIME_TYPES = {
    ".html": "text/html",
    ".css":  "text/css",
    ".js":   "application/javascript",
    ".json": "application/json",
    ".png":  "image/png",
    ".svg":  "image/svg+xml",
    ".ico":  "image/x-icon",
    ".woff": "font/woff",
    ".woff2":"font/woff2",
    ".ttf":  "font/ttf",
    ".map":  "application/json",
}

_DIST_DIR = os.path.join(_HERE, "web", "dist")


# ═══════════════════════════════════════════════════════════════════════════════
# Application state (mirrors what main_window.py tracks)
# ═══════════════════════════════════════════════════════════════════════════════

class AppState:
    """Central mutable state shared between the WS server and test executors."""

    def __init__(self) -> None:
        self.uuts: list[UUT] = []
        self.daq: SimpleDAQController = SimpleDAQController()
        self.testing_active: bool = False
        self.test_mode: str = "ibit"
        self.current_test_executor: Optional[Any] = None
        self.current_uut_index: int = -1
        self.batch_start_datetime: Optional[datetime] = None
        self.batch_end_time: Optional[float] = None
        self._starting_uut: bool = False

        # Vehicle / telemetry state (updated by executor callbacks)
        self.vehicle_mode: int = 0
        self.vehicle_regime: int = 0
        self.vehicle_armed: bool = False
        self.vehicle_relay_on: bool = False
        self.connection_healthy: bool = False
        self.ibit_substate: str = "IDLE"
        self.mistracking_flags: int = 0
        self.ibit_duration: float = 0.0
        self.actuator_data: dict = {}
        self.statistics: Optional[dict] = None
        self.iteration: int = 0

        # DAQ state
        self.daq_initialized: bool = False
        self.daq_device: Optional[str] = None
        self.daq_num_lines: int = 0
        self.daq_sitl_active: bool = False
        self.daq_devices: list[str] = []

        # Config
        self.test_config: dict = {
            "ibit_timeout": 300.0,
            "phase_timeout": 90.0,
            "arm_timeout": 60.0,
            "max_arm_iterations": 20,
            "skip_arm_for_ibit": False,
        }

        # Log directory
        self.project_root = _HERE
        self.log_directory = os.path.join(_HERE, "logs")
        self.report_directory = os.path.join(_HERE, "reports")
        os.makedirs(self.log_directory, exist_ok=True)
        os.makedirs(self.report_directory, exist_ok=True)

        # Load saved settings
        self._settings_path = os.path.join(_HERE, "app_settings.json")
        self.load_settings()

    def load_settings(self) -> None:
        """Load settings from app_settings.json if it exists."""
        try:
            if os.path.isfile(self._settings_path):
                with open(self._settings_path, "r") as f:
                    data = json.load(f)
                if "log_directory" in data:
                    self.log_directory = data["log_directory"]
                    os.makedirs(self.log_directory, exist_ok=True)
                if "report_directory" in data:
                    self.report_directory = data["report_directory"]
                    os.makedirs(self.report_directory, exist_ok=True)
                if "test_config" in data:
                    self.test_config.update(data["test_config"])
                if "test_mode" in data:
                    self.test_mode = data["test_mode"]
                for key in ("ibit_timeout", "phase_timeout", "arm_timeout", "max_arm_iterations"):
                    if key in data:
                        self.test_config[key] = data[key]
                if "skip_arm_for_ibit" in data:
                    self.test_config["skip_arm_for_ibit"] = data["skip_arm_for_ibit"]
                _log.info("Loaded settings from %s", self._settings_path)
        except Exception as e:
            _log.warning("Failed to load settings: %s", e)

    def save_settings(self) -> None:
        """Save current settings to app_settings.json."""
        try:
            data = {
                "log_directory": self.log_directory,
                "report_directory": self.report_directory,
                "test_config": self.test_config,
                "test_mode": self.test_mode,
                "connection_timeout": 10,
                "stabilization_delay": 2,
                "skip_state_management": False,
                "skip_arm_for_ibit": self.test_config.get("skip_arm_for_ibit", False),
                "ibit_timeout": self.test_config.get("ibit_timeout", 300),
                "phase_timeout": self.test_config.get("phase_timeout", 90),
                "arm_timeout": self.test_config.get("arm_timeout", 60),
                "max_arm_iterations": self.test_config.get("max_arm_iterations", 20),
                "playback_csv": "",
                "playback_type": "Both",
                "test_temperature_c": None,
            }
            with open(self._settings_path, "w") as f:
                json.dump(data, f, indent=2)
            _log.info("Saved settings to %s", self._settings_path)
        except Exception as e:
            _log.warning("Failed to save settings: %s", e)

    def to_sync_dict(self) -> dict:
        """Build the full state.sync payload for a newly connected client."""
        return {
            "uuts": [self._uut_dict(u) for u in self.uuts],
            "daq": {
                "initialized": self.daq_initialized,
                "device": self.daq_device,
                "num_lines": self.daq_num_lines,
                "sitl_active": self.daq_sitl_active,
                "devices": self.daq_devices,
            },
            "batch": self._batch_dict(),
            "vehicle": {
                "mode": self.vehicle_mode,
                "regime": self.vehicle_regime,
                "armed": self.vehicle_armed,
                "relay_on": self.vehicle_relay_on,
                "connection_healthy": self.connection_healthy,
            },
            "ibit": {
                "substate": self.ibit_substate,
                "mistracking_flags": self.mistracking_flags,
                "duration_seconds": self.ibit_duration,
            },
            "actuator": self.actuator_data,
            "statistics": self.statistics,
            "test_mode": self.test_mode,
            "config": self.test_config,
        }

    def _batch_dict(self) -> dict:
        elapsed = 0.0
        remaining = 0.0
        if self.testing_active and self.batch_end_time:
            now = time.monotonic()
            start_mono = getattr(self, "_batch_start_mono", now)
            elapsed = max(0.0, now - start_mono)
            remaining = max(0.0, self.batch_end_time - now)

        return {
            "active": self.testing_active,
            "mode": self.test_mode,
            "current_uut_index": self.current_uut_index,
            "current_uut_serial": (
                self.uuts[self.current_uut_index].serial_number
                if 0 <= self.current_uut_index < len(self.uuts)
                else None
            ),
            "elapsed_seconds": elapsed,
            "remaining_seconds": remaining,
            "total_uuts": len(self.uuts),
            "active_uuts": sum(
                1 for u in self.uuts if getattr(u, "status", "") != "Failed (3x)"
            ),
        }

    @staticmethod
    def _uut_dict(u: UUT) -> dict:
        # Map Python UUTStatus strings to frontend-expected values
        STATUS_MAP = {
            "Ready":       "READY",
            "Testing":     "TESTING",
            "Complete":    "PASSED",
            "Failed":      "FAILED",
            "Failed (3x)": "FAILED_PERMANENT",
            "Retry":       "RETRY",
            "Stopped":     "SKIPPED",
        }
        raw_status = u.status if isinstance(u.status, str) else str(u.status)
        normalized = STATUS_MAP.get(raw_status, raw_status.upper().replace(" ", "_").replace("(", "").replace(")", ""))
        return {
            "serial_number": u.serial_number,
            "ip_address": u.ip_address,
            "port": u.port,
            "relay_line": u.relay_line,
            "status": normalized,
            "iterations_completed": getattr(u, "iterations_completed", 0),
            "consecutive_failures": getattr(u, "consecutive_failures", 0),
            "soft_failures": getattr(u, "soft_failures", 0),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Broadcast manager — pushes events to all connected WebSocket clients
# ═══════════════════════════════════════════════════════════════════════════════

class Broadcaster:
    """Thread-safe broadcaster for WebSocket messages."""

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._clients: Set[ServerConnection] = set()
        self._loop = loop

    def register(self, ws: ServerConnection) -> None:
        self._clients.add(ws)

    def unregister(self, ws: ServerConnection) -> None:
        self._clients.discard(ws)

    def broadcast(self, msg_type: str, data: Any = None) -> None:
        """Send a message to all connected clients (thread-safe)."""
        payload = json.dumps({"type": msg_type, "data": data})
        if self._clients:
            asyncio.run_coroutine_threadsafe(
                self._broadcast_async(payload), self._loop
            )

    async def _broadcast_async(self, payload: str) -> None:
        dead: list[ServerConnection] = []
        for ws in self._clients:
            try:
                await ws.send(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)

    async def send_to(self, ws: ServerConnection, msg_type: str, data: Any = None) -> None:
        """Send a message to a specific client."""
        try:
            await ws.send(json.dumps({"type": msg_type, "data": data}))
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════════
# Executor callback bridge (replaces QtExecutorBridge for the web UI)
# ═══════════════════════════════════════════════════════════════════════════════

def wire_callbacks(state: AppState, broadcaster: Broadcaster) -> ExecutorCallbacks:
    """Create an ExecutorCallbacks that pushes events to WebSocket clients."""
    cb = ExecutorCallbacks()

    def _log(msg: str) -> None:
        ts = datetime.now().isoformat()
        broadcaster.broadcast("test.log", {"message": msg, "level": "info", "timestamp": ts})

    def _complete(success: bool, message: str) -> None:
        state.testing_active = False
        broadcaster.broadcast("test.complete", {"success": success, "message": message})
        broadcaster.broadcast("batch.status", state._batch_dict())

    def _mode(m: int) -> None:
        state.vehicle_mode = m
        broadcaster.broadcast("telemetry.vehicle_status", {
            "mode": m, "regime": state.vehicle_regime, "armed": state.vehicle_armed,
        })

    def _armed(armed: bool, regime: int) -> None:
        state.vehicle_armed = armed
        state.vehicle_regime = regime
        broadcaster.broadcast("telemetry.vehicle_status", {
            "mode": state.vehicle_mode, "regime": regime, "armed": armed,
        })

    def _ibit_state(s: str) -> None:
        state.ibit_substate = s
        broadcaster.broadcast("ibit.state", {"substate": s})

    def _actuator(d: dict) -> None:
        state.actuator_data = d
        broadcaster.broadcast("telemetry.actuator", d)

    def _connection_health(h: bool) -> None:
        state.connection_healthy = h
        broadcaster.broadcast("connection.health", {"healthy": h})

    def _relay(on: bool) -> None:
        state.vehicle_relay_on = on
        broadcaster.broadcast("daq.relay", {"on": on})

    def _mistracking(flags: int) -> None:
        state.mistracking_flags = flags
        broadcaster.broadcast("ibit.mistracking", {"flags": flags})

    def _statistics(s: Any) -> None:
        if hasattr(s, "__dict__"):
            state.statistics = s.__dict__
        elif isinstance(s, dict):
            state.statistics = s
        broadcaster.broadcast("test.statistics", state.statistics)

    def _duration(d: float) -> None:
        state.ibit_duration = d
        broadcaster.broadcast("test.duration", {"seconds": d})

    def _alert(msg: str) -> None:
        broadcaster.broadcast("alert", {"message": msg, "severity": "warning"})

    def _status(s: str) -> None:
        broadcaster.broadcast("test.status", {"status": s})

    def _iteration(i: int) -> None:
        state.iteration = i
        broadcaster.broadcast("test.iteration", {"iteration": i})

    def _progress(p: int) -> None:
        broadcaster.broadcast("test.progress", {"percent": p})

    cb.on_log = _log
    cb.on_complete = _complete
    cb.on_mode = _mode
    cb.on_armed_state = _armed
    cb.on_ibit_state = _ibit_state
    cb.on_actuator_feedback = _actuator
    cb.on_connection_health = _connection_health
    cb.on_relay_state = _relay
    cb.on_mistracking_update = _mistracking
    cb.on_statistics = _statistics
    cb.on_test_duration = _duration
    cb.on_alert = _alert
    cb.on_status = _status
    cb.on_iteration = _iteration
    cb.on_progress = _progress
    cb.on_time_expired = lambda: _complete(False, "Batch time expired")

    return cb


# ═══════════════════════════════════════════════════════════════════════════════
# Command handlers
# ═══════════════════════════════════════════════════════════════════════════════

class CommandHandler:
    """Processes commands received from the frontend."""

    def __init__(self, state: AppState, broadcaster: Broadcaster) -> None:
        self.state = state
        self.broadcaster = broadcaster

    async def handle(self, ws: ServerConnection, msg: dict) -> None:
        msg_type = msg.get("type", "")
        data = msg.get("data", {})

        handler_map = {
            "cmd.sync_state": self._sync_state,
            "cmd.detect_daq": self._detect_daq,
            "cmd.init_daq": self._init_daq,
            "cmd.launch_sitl": self._launch_sitl,
            "cmd.add_uut": self._add_uut,
            "cmd.edit_uut": self._edit_uut,
            "cmd.remove_uut": self._remove_uut,
            "cmd.start_test": self._start_test,
            "cmd.stop_test": self._stop_test,
            "cmd.emergency_stop": self._emergency_stop,
            "cmd.save_settings": self._save_settings,
            "cmd.save_uuts": self._save_uuts,
            "cmd.load_uuts": self._load_uuts,
        }

        handler = handler_map.get(msg_type)
        if handler:
            await handler(ws, data)
        elif msg_type.startswith("cmd.debug."):
            await self._handle_debug(msg_type, data)
        else:
            await self.broadcaster.send_to(ws, "error", {"message": f"Unknown command: {msg_type}"})

    async def _sync_state(self, ws: ServerConnection, _data: dict) -> None:
        await self.broadcaster.send_to(ws, "state.sync", self.state.to_sync_dict())

    async def _detect_daq(self, _ws: ServerConnection, _data: dict) -> None:
        devices = SimpleDAQController.detect_devices()
        self.state.daq_devices = devices
        self.broadcaster.broadcast("daq.status", {
            "initialized": self.state.daq_initialized,
            "device": self.state.daq_device,
            "num_lines": self.state.daq_num_lines,
            "sitl_active": self.state.daq_sitl_active,
            "devices": devices,
        })
        if devices:
            self.broadcaster.broadcast("test.log", {
                "message": f"Found {len(devices)} DAQ device(s): {', '.join(devices)}",
                "level": "info",
                "timestamp": datetime.now().isoformat(),
            })

    async def _init_daq(self, _ws: ServerConnection, data: dict) -> None:
        device = data.get("device", "")
        if not device:
            return
        success, message = self.state.daq.initialize(device, num_lines=8)
        if success:
            self.state.daq_initialized = True
            self.state.daq_device = device
            self.state.daq_num_lines = self.state.daq.num_lines
        self.broadcaster.broadcast("daq.status", {
            "initialized": self.state.daq_initialized,
            "device": self.state.daq_device,
            "num_lines": self.state.daq_num_lines,
            "sitl_active": self.state.daq_sitl_active,
            "devices": self.state.daq_devices,
        })
        self.broadcaster.broadcast("test.log", {
            "message": f"{'DAQ initialized: ' + message if success else 'DAQ failed: ' + message}",
            "level": "info" if success else "error",
            "timestamp": datetime.now().isoformat(),
        })

    async def _launch_sitl(self, _ws: ServerConnection, _data: dict) -> None:
        """Launch SITL simulation in a background thread."""
        def _bg() -> None:
            import time as _time
            from sim.vehicle import PandionVehicleSim
            from sim.mock_daq import MockDAQController
            import vehicle.connection as conn_mod

            self.broadcaster.broadcast("test.log", {
                "message": "LAUNCHING SITL SIMULATION",
                "level": "info",
                "timestamp": datetime.now().isoformat(),
            })

            sim_configs = [
                {"serial": "RR-SIM-001", "port": 19901, "relay": 0,
                 "ibit_pass": True, "sysid": 1},
                {"serial": "RR-SIM-002", "port": 19902, "relay": 1,
                 "ibit_pass": False, "mistracking_flags": 0xC0, "sysid": 2},
            ]

            # Patch connection for loopback
            dialect_dir = os.path.join(_HERE, "vehicle", "dialects")

            def _sitl_connect(ip_address: str, port: int, timeout: float = 10.0):
                if dialect_dir not in sys.path:
                    sys.path.insert(0, dialect_dir)
                from pymavlink import mavutil
                m = mavutil.mavlink_connection(
                    f"udpout:{ip_address}:{port}",
                    dialect="pandion_vehicle_roadrunner",
                    source_system=255, source_component=190,
                )
                for _ in range(5):
                    try:
                        m.mav.heartbeat_send(
                            mavutil.mavlink.MAV_TYPE_GCS,
                            mavutil.mavlink.MAV_AUTOPILOT_INVALID,
                            0, 0, mavutil.mavlink.MAV_STATE_ACTIVE,
                        )
                    except OSError:
                        pass
                    hb = m.recv_match(type="HEARTBEAT", blocking=True, timeout=1.0)
                    if hb and hb.get_srcSystem() != 255:
                        return m
                raise Exception(f"SITL vehicle not responding on {ip_address}:{port}")

            conn_mod.connect_to_vehicle = _sitl_connect

            sims = []
            for cfg in sim_configs:
                sim = PandionVehicleSim(
                    vehicle_port=cfg["port"],
                    sysid=cfg["sysid"],
                    ibit_pass=cfg["ibit_pass"],
                    mistracking_flags=cfg.get("mistracking_flags", 0),
                    boot_time_s=2.0,
                    ibit_duration_scale=0.5,
                    boot_monitors=[0, 1, 2, 3],
                )
                threading.Thread(target=sim.start, daemon=True,
                                 name=f"sitl-{cfg['port']}").start()
                sims.append(sim)

            _time.sleep(2.5)

            mock_daq = MockDAQController()
            mock_daq.initialize("SimDAQ/SITL")
            for i, cfg in enumerate(sim_configs):
                mock_daq.register_vehicle(cfg["relay"], sims[i])

            self.state.daq = mock_daq
            self.state.daq_initialized = True
            self.state.daq_device = "SimDAQ/SITL"
            self.state.daq_sitl_active = True

            # Pre-load UUTs
            self.state.uuts = []
            for cfg in sim_configs:
                self.state.uuts.append(
                    UUT(cfg["serial"], "127.0.0.1", cfg["port"], cfg["relay"])
                )

            self.broadcaster.broadcast("daq.status", {
                "initialized": True,
                "device": "SimDAQ/SITL",
                "num_lines": 8,
                "sitl_active": True,
                "devices": ["SimDAQ/SITL"],
            })
            self.broadcaster.broadcast("uut.update", {
                "uuts": [self.state._uut_dict(u) for u in self.state.uuts],
            })
            self.broadcaster.broadcast("test.log", {
                "message": "SITL ready — click Start to test (RR-SIM-001: PASS, RR-SIM-002: FAIL)",
                "level": "info",
                "timestamp": datetime.now().isoformat(),
            })

        threading.Thread(target=_bg, daemon=True, name="sitl-launcher").start()

    async def _add_uut(self, _ws: ServerConnection, data: dict) -> None:
        uut = UUT(
            data.get("serial_number", ""),
            data.get("ip_address", ""),
            data.get("port", 0),
            data.get("relay_line", 0),
        )
        self.state.uuts.append(uut)
        self.broadcaster.broadcast("uut.update", {
            "uuts": [self.state._uut_dict(u) for u in self.state.uuts],
        })

    async def _edit_uut(self, _ws: ServerConnection, data: dict) -> None:
        idx = data.get("index", -1)
        if 0 <= idx < len(self.state.uuts):
            self.state.uuts[idx] = UUT(
                data.get("serial_number", ""),
                data.get("ip_address", ""),
                data.get("port", 0),
                data.get("relay_line", 0),
            )
            self.broadcaster.broadcast("uut.update", {
                "uuts": [self.state._uut_dict(u) for u in self.state.uuts],
            })

    async def _remove_uut(self, _ws: ServerConnection, data: dict) -> None:
        idx = data.get("index", -1)
        if 0 <= idx < len(self.state.uuts):
            self.state.uuts.pop(idx)
            self.broadcaster.broadcast("uut.update", {
                "uuts": [self.state._uut_dict(u) for u in self.state.uuts],
            })

    async def _start_test(self, _ws: ServerConnection, data: dict) -> None:
        if self.state.testing_active:
            return
        if not self.state.daq_initialized and not self.state.daq_sitl_active:
            self.broadcaster.broadcast("error", {"message": "DAQ not initialized"})
            return
        if not self.state.uuts:
            self.broadcaster.broadcast("error", {"message": "No UUTs configured"})
            return

        duration = data.get("duration_seconds", 86400)
        mode = data.get("mode", "ibit")
        self.state.test_mode = mode
        self.state.testing_active = True
        self.state.batch_start_datetime = datetime.now()
        self.state.batch_end_time = time.monotonic() + duration
        self.state._batch_start_mono = time.monotonic()
        self.state.current_uut_index = -1

        # Apply config overrides from frontend
        if "config" in data and isinstance(data["config"], dict):
            self.state.test_config.update(data["config"])

        # Auto-save settings on test start
        self.state.save_settings()

        # Reset UUTs
        for uut in self.state.uuts:
            uut.status = UUTStatus.READY
            uut.iterations_completed = 0
            uut.consecutive_failures = 0

        self.broadcaster.broadcast("batch.status", self.state._batch_dict())
        self.broadcaster.broadcast("uut.update", {
            "uuts": [self.state._uut_dict(u) for u in self.state.uuts],
        })
        self.broadcaster.broadcast("test.log", {
            "message": f"BATCH START — {mode.upper()} — Duration: {duration}s",
            "level": "info",
            "timestamp": datetime.now().isoformat(),
        })

        # Start test execution in a background thread
        threading.Thread(
            target=self._run_batch, daemon=True, name="batch-runner",
        ).start()

    def _run_batch(self) -> None:
        """Round-robin test execution loop (runs on a background thread)."""
        while self.state.testing_active:
            if time.monotonic() >= self.state.batch_end_time:
                self.broadcaster.broadcast("test.log", {
                    "message": "Batch time expired",
                    "level": "info",
                    "timestamp": datetime.now().isoformat(),
                })
                self.state.testing_active = False
                self.broadcaster.broadcast("test.complete", {
                    "success": True, "message": "Batch complete",
                })
                break

            # Check if all UUTs are permanently failed
            active = [u for u in self.state.uuts if getattr(u, 'status', '') != 'Failed (3x)']
            if not active:
                self.state.testing_active = False
                self.broadcaster.broadcast("test.complete", {
                    "success": False, "message": "All UUTs permanently failed",
                })
                break

            # Guard against empty UUT list
            if not self.state.uuts:
                time.sleep(0.5)
                continue

            # Round-robin to next UUT
            self.state.current_uut_index = (self.state.current_uut_index + 1) % len(self.state.uuts)
            uut = self.state.uuts[self.state.current_uut_index]

            if getattr(uut, 'status', '') == 'Failed (3x)':
                continue

            uut.status = UUTStatus.TESTING
            self.broadcaster.broadcast("uut.update", {
                "uuts": [self.state._uut_dict(u) for u in self.state.uuts],
            })
            self.broadcaster.broadcast("batch.status", self.state._batch_dict())

            # Create callbacks
            callbacks = wire_callbacks(self.state, self.broadcaster)

            # Create and run executor
            if self.state.test_mode == "playback":
                executor = PlaybackTestExecutor(
                    uut, self.state.daq, self.state.batch_end_time,
                    stabilization_delay=2.0,
                    connection_timeout=10.0,
                    log_directory=self.state.log_directory,
                    test_start_datetime=self.state.batch_start_datetime,
                    playback_csv="",
                    playback_type="Both",
                    config=self.state.test_config,
                    callbacks=callbacks,
                )
            else:
                executor = UUTTestExecutor(
                    uut, self.state.daq, self.state.batch_end_time,
                    stabilization_delay=2.0,
                    connection_timeout=10.0,
                    log_directory=self.state.log_directory,
                    test_start_datetime=self.state.batch_start_datetime,
                    config=self.state.test_config,
                    callbacks=callbacks,
                )

            self.state.current_test_executor = executor

            # Run synchronously on this thread (executor.run() blocks)
            try:
                executor.run()
            except Exception as e:
                _log.exception("Executor failed for %s", uut.serial_number)
                self.broadcaster.broadcast("test.log", {
                    "message": f"Executor error: {e}",
                    "level": "error",
                    "timestamp": datetime.now().isoformat(),
                })

            # Update UUT status based on executor result
            self.broadcaster.broadcast("uut.update", {
                "uuts": [self.state._uut_dict(u) for u in self.state.uuts],
            })

        self.state.testing_active = False
        self.broadcaster.broadcast("batch.status", self.state._batch_dict())

    async def _stop_test(self, _ws: ServerConnection, _data: dict) -> None:
        self.state.testing_active = False
        if self.state.current_test_executor:
            try:
                self.state.current_test_executor.stop()
            except Exception:
                pass
        self.broadcaster.broadcast("test.log", {
            "message": "Test stopped by operator",
            "level": "warning",
            "timestamp": datetime.now().isoformat(),
        })
        self.broadcaster.broadcast("batch.status", self.state._batch_dict())

    async def _emergency_stop(self, _ws: ServerConnection, _data: dict) -> None:
        self.state.testing_active = False
        # Force all relays off
        try:
            self.state.daq.set_all_low()
        except Exception:
            pass
        if self.state.current_test_executor:
            try:
                self.state.current_test_executor.stop()
            except Exception:
                pass
        self.broadcaster.broadcast("test.log", {
            "message": "EMERGENCY STOP — All relays forced OFF",
            "level": "critical",
            "timestamp": datetime.now().isoformat(),
        })
        self.broadcaster.broadcast("alert", {
            "message": "EMERGENCY STOP activated — all relays OFF",
            "severity": "critical",
        })
        self.broadcaster.broadcast("batch.status", self.state._batch_dict())

    async def _save_settings(self, _ws: ServerConnection, _data: dict) -> None:
        self.state.save_settings()
        self.broadcaster.broadcast("test.log", {
            "message": "Settings saved",
            "level": "info",
            "timestamp": datetime.now().isoformat(),
        })

    async def _save_uuts(self, _ws: ServerConnection, data: dict) -> None:
        import json as _json
        path = data.get("path", "uut_config.json")
        try:
            uut_data = [self.state._uut_dict(u) for u in self.state.uuts]
            with open(path, "w") as f:
                _json.dump(uut_data, f, indent=2)
            self.broadcaster.broadcast("test.log", {
                "message": f"UUT config saved: {path}", "level": "info",
                "timestamp": datetime.now().isoformat(),
            })
        except Exception as e:
            self.broadcaster.broadcast("test.log", {
                "message": f"Failed to save UUTs: {e}", "level": "error",
                "timestamp": datetime.now().isoformat(),
            })

    async def _load_uuts(self, _ws: ServerConnection, data: dict) -> None:
        import json as _json
        path = data.get("path", "uut_config.json")
        try:
            with open(path) as f:
                uut_data = _json.load(f)
            self.state.uuts = [
                UUT(u["serial_number"], u["ip_address"], u["port"], u["relay_line"])
                for u in uut_data
            ]
            self.broadcaster.broadcast("uut.update", {
                "uuts": [self.state._uut_dict(u) for u in self.state.uuts],
            })
            self.broadcaster.broadcast("test.log", {
                "message": f"Loaded {len(self.state.uuts)} UUTs from {path}",
                "level": "info", "timestamp": datetime.now().isoformat(),
            })
        except Exception as e:
            self.broadcaster.broadcast("test.log", {
                "message": f"Failed to load UUTs: {e}", "level": "error",
                "timestamp": datetime.now().isoformat(),
            })

    async def _handle_debug(self, msg_type: str, data: dict) -> None:
        """Handle debug mode commands using a DebugConnection."""
        from testing.debug_connection import DebugConnection
        from vehicle.constants import MsgType, safe_int_field, is_armed
        from testing.helpers import _build_actuator_feedback_dict

        ts = lambda: datetime.now().isoformat()

        # ── Connect / disconnect ─────────────────────────────────────────
        if msg_type == "cmd.debug.connect":
            serial = data.get("serial", "")
            ip = data.get("ip", "")
            port = data.get("port", 0)

            # Disconnect existing
            if hasattr(self.state, "_debug_conn") and self.state._debug_conn:
                self.state._debug_conn.disconnect()

            conn = DebugConnection(ip, port, serial)
            conn.on_log = lambda msg: self.broadcaster.broadcast(
                "test.log", {"message": msg, "level": "info", "timestamp": ts()})
            conn.on_error = lambda msg: self.broadcaster.broadcast(
                "test.log", {"message": msg, "level": "error", "timestamp": ts()})

            def _on_message(msg: object) -> None:
                msg_type_str = msg.get_type()
                try:
                    if msg_type_str == MsgType.ACTUATION_SYS_STATUS:
                        fb = _build_actuator_feedback_dict(msg)
                        self.state.actuator_data = fb
                        self.broadcaster.broadcast("telemetry.actuator", fb)
                        mode = safe_int_field(msg, "actuation_state")
                        self.state.vehicle_mode = mode
                        self.broadcaster.broadcast("telemetry.vehicle_status", {
                            "mode": mode,
                            "regime": self.state.vehicle_regime,
                            "armed": self.state.vehicle_armed,
                        })
                    elif msg_type_str == MsgType.PANDION_STATUS:
                        regime = safe_int_field(msg, "flight_regime", 255)
                        armed = is_armed(regime)
                        self.state.vehicle_regime = regime
                        self.state.vehicle_armed = armed
                        self.broadcaster.broadcast("telemetry.vehicle_status", {
                            "mode": self.state.vehicle_mode,
                            "regime": regime,
                            "armed": armed,
                        })
                    elif msg_type_str == "COMMAND_ACK":
                        cmd = getattr(msg, "command", 0)
                        result = getattr(msg, "result", -1)
                        result_names = {0: "ACCEPTED", 1: "TEMPORARILY_REJECTED",
                                        2: "DENIED", 3: "UNSUPPORTED", 4: "FAILED"}
                        self.broadcaster.broadcast("test.log", {
                            "message": f"ACK cmd={cmd}: {result_names.get(result, str(result))}",
                            "level": "info" if result == 0 else "error",
                            "timestamp": ts(),
                        })
                    elif msg_type_str == MsgType.BMS_DATA:
                        voltage = getattr(msg, 'pack_voltage_mV', 0) or 0
                        current = getattr(msg, 'pack_current_cA', 0) or 0
                        soc = getattr(msg, 'state_of_charge_percent', 0) or 0
                        self.broadcaster.broadcast("telemetry.battery", {
                            "voltage_mV": voltage,
                            "current_cA": current,
                            "soc": max(0, min(100, soc)),
                        })
                    elif msg_type_str == MsgType.ENGINE_STATUS:
                        self.broadcaster.broadcast("telemetry.engine", {
                            "rpm": getattr(msg, 'eng_1_speed', 0) or 0,
                            "egt_C": getattr(msg, 'eng_1_egt_temp_degC', 0) or 0,
                            "fuel_pump_mA": getattr(msg, 'eng_1_fuel_pump_curr_mA', 0) or 0,
                        })

                    # Add to debug message stream
                    summary = ""
                    for field in ("actuation_state", "flight_regime", "eng_1_speed", "text"):
                        val = getattr(msg, field, None)
                        if val is not None:
                            summary = str(val)[:30] if field == "text" else f"{field}={val}"
                            break
                    self.broadcaster.broadcast("debug.message", {
                        "msg_type": msg_type_str, "summary": summary,
                    })
                except Exception:
                    pass

            conn.on_message = _on_message

            def _on_connected(serial: str) -> None:
                self.state.connection_healthy = True
                self.broadcaster.broadcast("connection.health", {"healthy": True})

            def _on_disconnected(serial: str) -> None:
                self.state.connection_healthy = False
                self.broadcaster.broadcast("connection.health", {"healthy": False})

            conn.on_connected = _on_connected
            conn.on_disconnected = _on_disconnected

            self.state._debug_conn = conn
            threading.Thread(target=conn.connect, daemon=True, name="debug-connect").start()
            return

        if msg_type == "cmd.debug.disconnect":
            if hasattr(self.state, "_debug_conn") and self.state._debug_conn:
                threading.Thread(
                    target=self.state._debug_conn.disconnect, daemon=True
                ).start()
                self.state._debug_conn = None
            return

        # ── Commands requiring an active connection ──────────────────────
        conn = getattr(self.state, "_debug_conn", None)
        if not conn or not conn.master or not conn.master_lock:
            self.broadcaster.broadcast("test.log", {
                "message": "[DEBUG] No active connection",
                "level": "error",
                "timestamp": ts(),
            })
            return

        try:
            if msg_type == "cmd.debug.mode_request":
                mode_id = data.get("mode_id", 0)
                with conn.master_lock:
                    conn.master.mav.pandion_rr_actuation_request_mode_send(
                        requested_mode=mode_id
                    )
                self.broadcaster.broadcast("test.log", {
                    "message": f"-> Mode request: {mode_id}",
                    "level": "info",
                    "timestamp": ts(),
                })

            elif msg_type == "cmd.debug.arm":
                arm = data.get("arm", True)
                force = data.get("force", False)
                from pymavlink import mavutil
                param2 = 21196 if force and arm else 0
                with conn.master_lock:
                    conn.master.mav.command_long_send(
                        conn.master.target_system, 1,
                        mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
                        0, float(arm), float(param2), 0, 0, 0, 0, 0,
                    )
                label = ("Force ARM" if force else "ARM") if arm else "DISARM"
                self.broadcaster.broadcast("test.log", {
                    "message": f"-> {label} command sent",
                    "level": "info",
                    "timestamp": ts(),
                })

            elif msg_type == "cmd.debug.param_set":
                name = data.get("name", "")
                value = data.get("value", 0)
                from pymavlink import mavutil
                with conn.master_lock:
                    conn.master.mav.param_set_send(
                        conn.master.target_system, 1,
                        name.encode("utf-8"),
                        float(value),
                        mavutil.mavlink.MAV_PARAM_TYPE_UINT8,
                    )
                self.broadcaster.broadcast("test.log", {
                    "message": f"-> PARAM_SET {name} = {value}",
                    "level": "info",
                    "timestamp": ts(),
                })

            elif msg_type == "cmd.debug.monitor_override":
                cmd = data.get("cmd", 0)
                monitor_id = data.get("monitor_id", 0)
                cmd_names = {0: "CANCEL", 1: "SUPPRESS", 2: "FORCE_FAULT"}
                with conn.master_lock:
                    conn.master.mav.pandion_monitor_override_cmd_send(
                        override_cmd=cmd, monitor_id=monitor_id,
                    )
                self.broadcaster.broadcast("test.log", {
                    "message": f"-> Monitor {monitor_id}: {cmd_names.get(cmd, str(cmd))}",
                    "level": "info",
                    "timestamp": ts(),
                })

            elif msg_type == "cmd.debug.raw_command":
                cmd_id = data.get("cmd_id", 0)
                param1 = data.get("param1", 0.0)
                with conn.master_lock:
                    conn.master.mav.command_long_send(
                        conn.master.target_system, 1,
                        int(cmd_id), 0, param1, 0, 0, 0, 0, 0, 0,
                    )
                self.broadcaster.broadcast("test.log", {
                    "message": f"-> COMMAND_LONG cmd={cmd_id} p1={param1}",
                    "level": "info",
                    "timestamp": ts(),
                })

        except Exception as e:
            self.broadcaster.broadcast("test.log", {
                "message": f"[DEBUG] Command failed: {e}",
                "level": "error",
                "timestamp": ts(),
            })


# ═══════════════════════════════════════════════════════════════════════════════
# WebSocket server
# ═══════════════════════════════════════════════════════════════════════════════

async def ws_handler(
    ws: ServerConnection,
    state: AppState,
    broadcaster: Broadcaster,
    cmd_handler: CommandHandler,
) -> None:
    """Handle a single WebSocket client connection."""
    broadcaster.register(ws)
    remote = ws.remote_address
    _log.info("Client connected: %s", remote)

    try:
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await broadcaster.send_to(ws, "error", {"message": "Invalid JSON"})
                continue

            try:
                await cmd_handler.handle(ws, msg)
            except Exception as e:
                _log.exception("Command handler error")
                await broadcaster.send_to(ws, "error", {"message": str(e)})
    except websockets.ConnectionClosed:
        pass
    finally:
        broadcaster.unregister(ws)
        _log.info("Client disconnected: %s", remote)


async def main(auto_sitl: bool = False) -> None:
    loop = asyncio.get_running_loop()
    state = AppState()
    broadcaster = Broadcaster(loop)
    cmd_handler = CommandHandler(state, broadcaster)

    _log.info("Starting WebSocket server on ws://0.0.0.0:%d", WS_PORT)

    # ── Static file HTTP server ───────────────────────────────────────────
    has_dist = os.path.isdir(_DIST_DIR) and os.path.isfile(os.path.join(_DIST_DIR, "index.html"))

    async def _http_handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Minimal HTTP/1.1 static file server for the built React app."""
        try:
            request_line = await asyncio.wait_for(reader.readline(), timeout=5.0)
            if not request_line:
                writer.close()
                return

            parts = request_line.decode("utf-8", errors="replace").strip().split()
            method = parts[0] if len(parts) >= 1 else "GET"
            path = parts[1] if len(parts) >= 2 else "/"

            # Consume remaining headers
            while True:
                line = await asyncio.wait_for(reader.readline(), timeout=5.0)
                if line in (b"\r\n", b"\n", b""):
                    break

            if method != "GET":
                body = b"Method Not Allowed"
                writer.write(b"HTTP/1.1 405 Method Not Allowed\r\nContent-Length: %d\r\n\r\n" % len(body))
                writer.write(body)
                await writer.drain()
                writer.close()
                return

            # Strip query string
            path = path.split("?")[0]

            # Map URL to file
            if path == "/":
                path = "/index.html"

            file_path = os.path.normpath(os.path.join(_DIST_DIR, path.lstrip("/")))

            # Security: prevent directory traversal
            if not file_path.startswith(os.path.normpath(_DIST_DIR)):
                file_path = os.path.join(_DIST_DIR, "index.html")

            # If file doesn't exist, serve index.html (SPA routing)
            if not os.path.isfile(file_path):
                file_path = os.path.join(_DIST_DIR, "index.html")

            ext = os.path.splitext(file_path)[1].lower()
            content_type = _MIME_TYPES.get(ext, "application/octet-stream")

            with open(file_path, "rb") as f:
                body = f.read()

            # Cache hashed assets (js/css) long-term; don't cache index.html
            is_asset = "/assets/" in file_path.replace("\\", "/")
            cache = "public, max-age=31536000, immutable" if is_asset else "no-cache"

            header = (
                f"HTTP/1.1 200 OK\r\n"
                f"Content-Type: {content_type}\r\n"
                f"Content-Length: {len(body)}\r\n"
                f"Cache-Control: {cache}\r\n"
                f"Access-Control-Allow-Origin: *\r\n"
                f"\r\n"
            )
            writer.write(header.encode())
            writer.write(body)
            await writer.drain()

        except Exception:
            try:
                writer.write(b"HTTP/1.1 500 Internal Server Error\r\n\r\n")
                await writer.drain()
            except Exception:
                pass
        finally:
            try:
                writer.close()
            except Exception:
                pass

    http_server = None
    if has_dist:
        http_server = await asyncio.start_server(_http_handler, "0.0.0.0", HTTP_PORT)
        _log.info("HTTP server ready on http://0.0.0.0:%d (serving web/dist/)", HTTP_PORT)
    else:
        _log.warning("web/dist/ not found — run 'npx vite build' in web/ first. "
                      "HTTP file server disabled; use 'npx vite' for dev mode.")

    async with serve(
        lambda ws: ws_handler(ws, state, broadcaster, cmd_handler),
        "0.0.0.0",
        WS_PORT,
    ):
        _log.info("WebSocket server ready on ws://0.0.0.0:%d", WS_PORT)

        if has_dist:
            _log.info("Open http://localhost:%d in your browser", HTTP_PORT)
        else:
            _log.info("Run 'npx vite' in web/ and open http://localhost:5173")

        if auto_sitl:
            _log.info("Auto-launching SITL...")
            await cmd_handler._launch_sitl(None, {})  # type: ignore[arg-type]

        # Periodic batch status updates (elapsed/remaining timer)
        async def _batch_ticker() -> None:
            while True:
                await asyncio.sleep(1.0)
                if state.testing_active and state.batch_end_time:
                    now = time.monotonic()
                    elapsed = now - getattr(state, "_batch_start_mono", now)
                    remaining = max(0, state.batch_end_time - now)
                    broadcaster.broadcast("batch.status", {
                        "active": True,
                        "mode": state.test_mode,
                        "current_uut_index": state.current_uut_index,
                        "current_uut_serial": (
                            state.uuts[state.current_uut_index].serial_number
                            if 0 <= state.current_uut_index < len(state.uuts)
                            else None
                        ),
                        "elapsed_seconds": elapsed,
                        "remaining_seconds": remaining,
                        "total_uuts": len(state.uuts),
                        "active_uuts": sum(
                            1 for u in state.uuts
                            if getattr(u, 'status', '') != 'Failed (3x)'
                        ),
                    })

        asyncio.create_task(_batch_ticker())

        await asyncio.Future()  # run forever


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Roadrunner Flight Test — WebSocket backend")
    parser.add_argument("--sitl", action="store_true", help="Auto-launch SITL on startup")
    parser.add_argument("--open", action="store_true", help="Auto-open browser on startup")
    args = parser.parse_args()

    if args.open:
        import webbrowser
        # Delay browser open so server has time to start
        def _open_browser():
            import time as _t
            _t.sleep(3)
            url = f"http://localhost:{HTTP_PORT}"
            _log.info("Opening %s", url)
            webbrowser.open(url)
        threading.Thread(target=_open_browser, daemon=True).start()

    try:
        asyncio.run(main(auto_sitl=args.sitl))
    except KeyboardInterrupt:
        _log.info("Shutting down")
