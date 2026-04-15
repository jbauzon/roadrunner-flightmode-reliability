from __future__ import annotations

"""
Shared executor mixin for IBIT and Playback test executors.
"""
import os
import time
import threading
from collections import defaultdict, deque
from typing import Any, Dict, Optional

from pymavlink import mavutil
from vehicle.connection import connect_to_vehicle
from vehicle.preparation import UUTPreparation
from vehicle.constants import (
    RELAY_DISABLE_MAX_ATTEMPTS,
    RELAY_DISABLE_RETRY_DELAY,
    HEARTBEAT_BURST_INTERVAL,
)
from .callbacks import ExecutorCallbacks, PreparationCallbacks
from .logger import TelemetryLogger
from .error_logger import ErrorLogger
from .helpers import _build_actuator_feedback_dict


# ════════════════════════════════════════════════════════════════════════════════
# Shared executor methods (mixin)
# ════════════════════════════════════════════════════════════════════════════════

class _ExecutorMixin:
    """
    Shared methods for IBIT and Playback test executors.

    Provides: heartbeat worker, emergency relay disable, wait-for-message,
    MAVLink connection setup, stop, and resource cleanup helpers.

    Subclasses must set ``self.cb`` to an :class:`ExecutorCallbacks` instance
    before calling any mixin methods.
    """

    def _init_executor(self, uut: Any, daq_controller: Any, batch_end_time: float,
                       stabilization_delay: float, connection_timeout: float,
                       log_directory: str, test_start_datetime: Any, config: Optional[dict]) -> None:
        """Common field initialization — call from subclass __init__."""
        self.cb: ExecutorCallbacks = None  # set by subclass __init__
        self.uut = uut
        self.daq = daq_controller
        self.batch_end_time = batch_end_time
        self.stabilization_delay = stabilization_delay
        self.connection_timeout = connection_timeout
        self.log_directory = log_directory
        self.test_start_datetime = test_start_datetime
        self.config = config or {}

        self.running = False
        self.master = None
        self.telemetry_logger = None
        self.preparation = None
        self.heartbeat_thread = None
        self.heartbeat_count = 0
        self.master_lock = threading.Lock()

        # Persistent error log — shared across all iterations for this UUT
        self.error_log = ErrorLogger(log_directory)

        # Dispatch queues — populated by _msg_dispatch_worker (the sole socket reader)
        self._msg_queues: Dict[str, deque] = defaultdict(lambda: deque(maxlen=100))
        self._all_msgs_queue: deque = deque(maxlen=200)
        self._dispatch_thread = None

        # Sysid filter — set after connection in _connect_and_start_heartbeat
        self._expected_sysid = None

        # BAD_DATA streak counter for dispatch worker
        self._bad_data_streak = 0

    # ── Connection helpers ──────────────────────────────────────────────

    def _connect_and_start_heartbeat(self) -> None:
        """Connect to the vehicle and start the GCS heartbeat thread."""
        self.cb.on_status("Connecting to UUT (no load)...")
        self.master = connect_to_vehicle(
            self.uut.ip_address, self.uut.port, self.connection_timeout
        )
        self.cb.on_log(
            f"\u2713 Connected to {self.uut.ip_address}:{self.uut.port}"
        )

        # Learn the vehicle's sysid BEFORE starting the dispatch worker
        # (dispatch worker would consume the heartbeat otherwise)
        hb = self.master.recv_match(type='HEARTBEAT', blocking=True, timeout=3.0)
        if hb and hb.get_srcSystem() != 255:
            candidate_sysid = hb.get_srcSystem()
            # Verify with a second heartbeat to avoid stale buffer packets (S-1)
            hb2 = self.master.recv_match(type='HEARTBEAT', blocking=True, timeout=2.0)
            if hb2 and hb2.get_srcSystem() != 255:
                if hb2.get_srcSystem() == candidate_sysid:
                    self._expected_sysid = candidate_sysid
                    self.cb.on_log(f"  Vehicle sysid: {self._expected_sysid} (verified)")
                else:
                    # Two different sysids — take the more recent one
                    self._expected_sysid = hb2.get_srcSystem()
                    self.cb.on_log(
                        f"  \u26a0 Sysid mismatch in buffer ({candidate_sysid} vs "
                        f"{hb2.get_srcSystem()}) \u2014 using {self._expected_sysid}"
                    )
            else:
                self._expected_sysid = candidate_sysid
                self.cb.on_log(f"  Vehicle sysid: {self._expected_sysid}")

        # Start dispatch worker AFTER learning sysid — preparation
        # uses _wait_for_message which reads from queues populated by this worker.
        self._dispatch_thread = threading.Thread(
            target=self._msg_dispatch_worker, daemon=True
        )
        self._dispatch_thread.start()

        self.cb.on_log("\u2192 Starting GCS heartbeat sender...")
        self.heartbeat_thread = threading.Thread(
            target=self._heartbeat_worker, daemon=True
        )
        self.heartbeat_thread.start()
        self.cb.on_log(
            "  Waiting for vehicle to stabilize with GCS heartbeats..."
        )
        time.sleep(2.0)

    def _open_telemetry_logger(self, test_mode: str = 'ibit') -> None:
        """Create, open, and connect the telemetry logger."""
        self.telemetry_logger = TelemetryLogger(
            self.log_directory,
            self.uut.serial_number,
            self.test_start_datetime,
            logging_mode=TelemetryLogger.MODE_IBIT_FOCUSED,
            test_mode=test_mode,
            on_log=self.cb.on_log,
        )
        if not self.telemetry_logger.open():
            raise Exception("Failed to open log file")
        self.uut.log_file = self.telemetry_logger.get_current_log_path()

    def _create_preparation(self) -> None:
        """Instantiate UUTPreparation and wire its callbacks."""
        prep_cb = PreparationCallbacks()
        prep_cb.on_log = self.cb.on_log
        prep_cb.on_progress = self.cb.on_status
        prep_cb.on_armed_state = self.cb.on_armed_state
        prep_cb.on_mode = self.cb.on_mode
        prep_cb.on_connection_health = self.cb.on_connection_health
        prep_cb.on_actuator_feedback = self.cb.on_actuator_feedback
        prep_cb.on_alert = self.cb.on_alert
        self.preparation = UUTPreparation(
            self.master, self.config, self.telemetry_logger,
            callbacks=prep_cb,
            msg_queues=self._msg_queues,
            error_log=self.error_log,
        )
        # Store serial on preparation for error log context
        self.preparation._serial = self.uut.serial_number
        self.preparation._iteration = lambda: self.uut.iterations_completed

    def _enable_relay(self, label: str = "test") -> None:
        """Enable the load relay with stabilization and heartbeat check."""
        self.cb.on_status(f"Enabling load relay for {label}...")
        self.cb.on_log("\n" + "=" * 60)
        self.cb.on_log("ENABLING LOAD RELAY")
        self.cb.on_log("=" * 60)

        ok, msg = self._set_line_with_timeout(self.uut.relay_line, True)
        if not ok:
            raise Exception(f"Failed to enable relay: {msg}")
        if self.telemetry_logger:
            self.telemetry_logger.log_relay_state(self.uut.relay_line, True)

        self.cb.on_log(
            f"\u2713 Relay {self.uut.relay_line} ENABLED - Load applied"
        )
        self.cb.on_relay_state(True)
        self.cb.on_log(
            f"  Waiting {self.stabilization_delay}s for stabilization..."
        )
        time.sleep(self.stabilization_delay)

        hb = self.master.wait_heartbeat(timeout=2.0)
        if not hb:
            raise Exception("Lost connection after applying load")
        self.cb.on_log("\u2713 Vehicle responsive under load")
        self.cb.on_log("=" * 60 + "\n")

    def _set_line_with_timeout(self, line: int, state: bool,
                                timeout_s: float = 10.0):
        """Call set_line with a hard timeout to prevent DAQ hangs (S-3).

        Returns:
            (ok: bool, msg: str)
        """
        result = [None, None]

        def _call():
            result[0], result[1] = self.daq.set_line(line, state)

        t = threading.Thread(target=_call, daemon=True)
        t.start()
        t.join(timeout=timeout_s)
        if t.is_alive():
            return False, f"set_line timed out after {timeout_s}s (DAQ may be hung)"
        if result[0] is None:
            return False, "set_line returned no result"
        return result[0], result[1]

    # ── Heartbeat ───────────────────────────────────────────────────────

    def _heartbeat_worker(self) -> None:
        """Send GCS heartbeats at 1 Hz with initial burst."""
        self.cb.on_log("\u2713 Heartbeat sender started (1 Hz)")

        # Initial burst
        try:
            for _ in range(3):
                with self.master_lock:
                    if self.master:
                        self.master.mav.heartbeat_send(
                            mavutil.mavlink.MAV_TYPE_GCS,
                            mavutil.mavlink.MAV_AUTOPILOT_INVALID,
                            0, 0,
                            mavutil.mavlink.MAV_STATE_ACTIVE,
                        )
                        self.heartbeat_count += 1
                time.sleep(HEARTBEAT_BURST_INTERVAL)
            self.cb.on_log("  \u2713 Initial heartbeat burst sent")
        except Exception as e:
            self.cb.on_log(f"\u26a0 Initial heartbeat error: {e}")

        # Regular 1 Hz
        while self.running:
            try:
                with self.master_lock:
                    if self.master:
                        self.master.mav.heartbeat_send(
                            mavutil.mavlink.MAV_TYPE_GCS,
                            mavutil.mavlink.MAV_AUTOPILOT_INVALID,
                            0, 0,
                            mavutil.mavlink.MAV_STATE_ACTIVE,
                        )
                        self.heartbeat_count += 1
                if self.heartbeat_count % 60 == 0:
                    self.cb.on_log(
                        f"  \u2764 Heartbeat active ({self.heartbeat_count} sent)"
                    )
            except BaseException as e:
                self.cb.on_log(f"\u26a0 Heartbeat send error: {type(e).__name__}: {e}")
                if not self.running:
                    break
            time.sleep(1.0)

        self.cb.on_log(
            f"\u2713 Heartbeat sender stopped (total sent: {self.heartbeat_count})"
        )

    # ── Emergency relay disable ─────────────────────────────────────────

    def _emergency_relay_disable(self) -> None:
        """
        Emergency relay disable with retry logic and verification.

        CRITICAL SAFETY FUNCTION: Must succeed or alert user.
        """
        if not self.daq or not self.uut:
            return

        self.cb.on_log("=" * 60)
        self.cb.on_log("\u26a0\u26a0\u26a0 EMERGENCY RELAY DISABLE \u26a0\u26a0\u26a0")
        self.cb.on_log("=" * 60)
        self.cb.on_log(
            f"\u2192 Attempting to disable relay {self.uut.relay_line}..."
        )

        max_attempts = RELAY_DISABLE_MAX_ATTEMPTS
        retry_delay = RELAY_DISABLE_RETRY_DELAY

        for attempt in range(1, max_attempts + 1):
            try:
                self.cb.on_log(f"  Attempt {attempt}/{max_attempts}...")
                ok, msg = self._set_line_with_timeout(self.uut.relay_line, False)
                if ok:
                    self.cb.on_log(
                        f"  \u2713 Relay {self.uut.relay_line} DISABLED "
                        f"(attempt {attempt})"
                    )
                    if self.telemetry_logger:
                        try:
                            self.telemetry_logger.log_relay_state(
                                self.uut.relay_line, False
                            )
                        except Exception as log_err:
                            self.cb.on_log(
                                f"  \u26a0 Logging error: {log_err}"
                            )
                    self.cb.on_relay_state(False)
                    self.cb.on_log(
                        "\u2713 Emergency relay disable SUCCESSFUL"
                    )
                    self.cb.on_log("=" * 60)
                    return
                else:
                    self.cb.on_log(
                        f"  \u2717 Attempt {attempt} failed: {msg}"
                    )
            except BaseException as err:
                self.cb.on_log(
                    f"  \u2717 Attempt {attempt} exception: "
                    f"{type(err).__name__}: {err}"
                )

            if attempt < max_attempts:
                self.cb.on_log(f"  \u2192 Retrying in {retry_delay}s...")
                time.sleep(retry_delay)

        # All attempts failed
        self.cb.on_log("")
        self.cb.on_log(
            f"\u2717\u2717\u2717 CRITICAL: RELAY {self.uut.relay_line} "
            f"DISABLE FAILED AFTER {max_attempts} ATTEMPTS \u2717\u2717\u2717"
        )
        self.cb.on_log("\u26a0 MANUAL INTERVENTION REQUIRED \u26a0")
        self.cb.on_log("\u26a0 VERIFY HARDWARE IS POWERED OFF \u26a0")
        self.cb.on_log("=" * 60)

        self.cb.on_alert(
            f"CRITICAL: RELAY {self.uut.relay_line} CONTROL FAILURE - "
            f"CHECK HARDWARE"
        )
        self.cb.on_log("=" * 60)
        self.cb.on_log("\u26a0\u26a0\u26a0 SAFETY WARNING \u26a0\u26a0\u26a0")
        self.cb.on_log(f"RELAY {self.uut.relay_line} CANNOT BE DISABLED ELECTRONICALLY")
        self.cb.on_log("VEHICLE MAY STILL BE POWERED AND IN IBIT MODE")
        self.cb.on_log("ACTION REQUIRED: Manually disconnect vehicle power immediately")
        self.cb.on_log("Then click Stop to acknowledge and clear the alert")
        self.cb.on_log("=" * 60)

        # Persist to error log
        self.error_log.critical(
            'RELAY',
            self.uut.serial_number,
            getattr(self.uut, 'iterations_completed', 0),
            f"Relay {self.uut.relay_line} DISABLE FAILED after {max_attempts} attempts — MANUAL POWER-OFF REQUIRED",
            {'relay_line': self.uut.relay_line, 'attempts': max_attempts},
        )
        if self.telemetry_logger:
            try:
                self.telemetry_logger.log_test_event(
                    'RELAY_DISABLE_CRITICAL_FAILURE',
                    f'Failed to disable relay {self.uut.relay_line} '
                    f'after {max_attempts} attempts - MANUAL INTERVENTION REQUIRED',
                )
            except Exception:
                pass

    # ── Message helpers ─────────────────────────────────────────────────

    def _msg_dispatch_worker(self) -> None:
        """Single socket reader — routes all incoming messages to per-type queues.

        This is the ONLY thread that calls recv_match on the socket.
        All other consumers read from _msg_queues or _all_msgs_queue.

        C-3: No master_lock held during recv — dispatch worker is the sole
        reader, so no lock is needed.  master_lock is kept only for SEND
        operations (heartbeat, mode requests).
        """
        try:
            while self.running:
                try:
                    # Don't hold master_lock during recv — dispatch worker is
                    # the sole reader; no other thread calls recv_match.
                    msg = self.master.recv_match(blocking=False)
                    if msg:
                        msg_type = msg.get_type()
                        if msg_type != 'BAD_DATA':
                            # Filter by expected vehicle sysid if known
                            if self._expected_sysid is None or msg.get_srcSystem() == self._expected_sysid:
                                self._msg_queues[msg_type].append(msg)
                                self._all_msgs_queue.append(msg)
                            # else: silently discard foreign sysid messages
                            self._bad_data_streak = 0
                        else:
                            self._bad_data_streak = getattr(self, '_bad_data_streak', 0) + 1
                            if self._bad_data_streak % 100 == 0:
                                self.cb.on_log(
                                    f"\u26a0 {self._bad_data_streak} consecutive BAD_DATA messages "
                                    f"\u2014 check MAVLink dialect version"
                                )
                    else:
                        time.sleep(0.002)  # 2 ms idle — 500 Hz max polling rate
                except OSError as e:
                    # WinError 10054: ICMP port-unreachable from sim restart.
                    # The socket is still usable — just skip this recv.
                    if getattr(e, 'winerror', None) == 10054:
                        time.sleep(0.01)
                        continue
                    raise
                except Exception:
                    time.sleep(0.01)
        except BaseException as e:
            # Dispatch worker died — this is critical, abort the test
            try:
                self.cb.on_log(
                    f"\u2717 CRITICAL: Message dispatch worker died: {type(e).__name__}: {e}"
                )
                self.cb.on_alert(
                    "CRITICAL: Message dispatch worker died \u2014 aborting test and disabling relay"
                )
                self.error_log.critical(
                    'SYSTEM', getattr(self.uut, 'serial_number', 'unknown'), 0,
                    f'Dispatch worker died: {type(e).__name__}: {e}',
                )
            except Exception:
                pass
            # Stop the executor and emergency-disable relay
            self.running = False
            self._emergency_relay_disable()

    def _wait_for_message(self, msg_type: str, timeout: float = 5.0) -> Optional[Any]:
        """Wait for a specific MAVLink message type from the dispatch queue."""
        deadline = time.monotonic() + timeout
        q = self._msg_queues[msg_type]
        while time.monotonic() < deadline:
            if q:
                return q.popleft()
            remaining = deadline - time.monotonic()
            time.sleep(min(0.005, max(0.0, remaining)))
        return None

    # ── Stop / cleanup helpers ──────────────────────────────────────────

    def stop(self) -> None:
        """Signal the executor to stop."""
        self.running = False
        if self.telemetry_logger:
            self.telemetry_logger.log_test_event(
                'TEST_STOPPED', 'Test stopped by user request'
            )

    def _close_resources(self) -> None:
        """Close telemetry logger and MAVLink connection."""
        if self.telemetry_logger:
            try:
                self.telemetry_logger.close()
            except Exception:
                pass
        if self.master:
            try:
                self.master.close()
            except Exception:
                pass

    def _stop_heartbeat(self) -> None:
        """Stop the heartbeat sender thread."""
        self.running = False
        if self.heartbeat_thread and self.heartbeat_thread.is_alive():
            self.heartbeat_thread.join(timeout=2.0)
            if self.heartbeat_thread.is_alive():
                self.cb.on_log(
                    "\u26a0 Heartbeat thread did not stop cleanly"
                )
            else:
                self.cb.on_log("\u2713 Heartbeat sender stopped")
