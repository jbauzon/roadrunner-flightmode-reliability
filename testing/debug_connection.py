"""
testing.debug_connection -- Lightweight MAVLink connection for debug mode.

Establishes a MAVLink connection to a UUT, sends GCS heartbeats at 1Hz,
and routes all incoming messages to registered consumers.
Used by Debug Mode to inspect/command the vehicle without running a test.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Callable, Optional, Any

import vehicle.connection as _vehicle_conn
from vehicle.constants import MsgType


class DebugConnection:
    """
    Minimal MAVLink connection for debug mode.

    Sends heartbeats, dispatches incoming messages to registered callbacks.
    Does NOT run any test sequence.
    """

    def __init__(self, ip: str, port: int, serial: str,
                 connection_timeout: float = 10.0):
        self.ip = ip
        self.port = port
        self.serial = serial
        self.connection_timeout = connection_timeout

        self.master = None
        self.master_lock = threading.Lock()
        self._running = False
        self._expected_sysid = None
        self._heartbeat_count = 0

        # Dispatch queues (same pattern as _ExecutorMixin)
        self._msg_queues: dict = defaultdict(lambda: deque(maxlen=100))
        self._all_msgs_queue: deque = deque(maxlen=200)

        # Callbacks
        self.on_connected: Callable[[str], None] = lambda serial: None
        self.on_disconnected: Callable[[str], None] = lambda serial: None
        self.on_message: Callable[[Any], None] = lambda msg: None
        self.on_log: Callable[[str], None] = lambda msg: None
        self.on_error: Callable[[str], None] = lambda msg: None

        self._dispatch_thread: Optional[threading.Thread] = None
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._bad_data_streak = 0

    def connect(self) -> bool:
        """Connect to the vehicle. Returns True on success."""
        try:
            self.on_log(f"Connecting to {self.serial} ({self.ip}:{self.port})...")
            self.master = _vehicle_conn.connect_to_vehicle(self.ip, self.port, self.connection_timeout)
            self.on_log(f"  \u2713 Connected to {self.serial}")

            # Learn sysid before starting dispatch
            hb = self.master.recv_match(type='HEARTBEAT', blocking=True, timeout=3.0)
            if hb and hb.get_srcSystem() != 255:
                self._expected_sysid = hb.get_srcSystem()
                self.on_log(f"  Vehicle sysid: {self._expected_sysid}")

            self._running = True

            # Start dispatch worker
            self._dispatch_thread = threading.Thread(
                target=self._dispatch_worker, daemon=True,
                name=f'debug-dispatch-{self.serial}'
            )
            self._dispatch_thread.start()

            # Start heartbeat sender
            self._heartbeat_thread = threading.Thread(
                target=self._heartbeat_worker, daemon=True,
                name=f'debug-hb-{self.serial}'
            )
            self._heartbeat_thread.start()

            self.on_connected(self.serial)
            return True

        except Exception as e:
            self.on_error(f"Connection failed: {e}")
            return False

    def disconnect(self) -> None:
        """Disconnect and stop all threads."""
        self._running = False
        if self._dispatch_thread and self._dispatch_thread.is_alive():
            self._dispatch_thread.join(timeout=2.0)
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            self._heartbeat_thread.join(timeout=2.0)
        if self.master:
            try:
                self.master.close()
            except Exception:
                pass
            self.master = None
        self.on_disconnected(self.serial)
        self.on_log(f"  Disconnected from {self.serial}")

    def _dispatch_worker(self) -> None:
        """Read all incoming messages and dispatch to queues and callbacks."""
        try:
            while self._running:
                try:
                    msg = self.master.recv_match(blocking=False)
                    if msg:
                        msg_type = msg.get_type()
                        if msg_type != 'BAD_DATA':
                            sysid = msg.get_srcSystem()
                            if self._expected_sysid is None or sysid == self._expected_sysid:
                                self._msg_queues[msg_type].append(msg)
                                self._all_msgs_queue.append(msg)
                                self.on_message(msg)
                        else:
                            self._bad_data_streak += 1
                    else:
                        time.sleep(0.002)
                except OSError as e:
                    if getattr(e, 'winerror', None) == 10054:
                        time.sleep(0.01)
                        continue
                    raise
                except Exception:
                    time.sleep(0.01)
        except BaseException as e:
            self.on_error(f"Dispatch worker died: {e}")
            self._running = False

    def _heartbeat_worker(self) -> None:
        """Send GCS heartbeats at 1Hz."""
        from pymavlink import mavutil
        # Initial burst
        for _ in range(3):
            try:
                with self.master_lock:
                    if self.master:
                        self.master.mav.heartbeat_send(
                            mavutil.mavlink.MAV_TYPE_GCS,
                            mavutil.mavlink.MAV_AUTOPILOT_INVALID,
                            0, 0, mavutil.mavlink.MAV_STATE_ACTIVE,
                        )
                        self._heartbeat_count += 1
            except Exception:
                pass
            time.sleep(0.1)

        while self._running:
            try:
                with self.master_lock:
                    if self.master:
                        self.master.mav.heartbeat_send(
                            mavutil.mavlink.MAV_TYPE_GCS,
                            mavutil.mavlink.MAV_AUTOPILOT_INVALID,
                            0, 0, mavutil.mavlink.MAV_STATE_ACTIVE,
                        )
                        self._heartbeat_count += 1
            except Exception:
                pass
            time.sleep(1.0)
