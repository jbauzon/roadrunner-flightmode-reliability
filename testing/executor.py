from __future__ import annotations

"""
Test Executor - Orchestrates IBIT test sequence

This module manages the complete test lifecycle:
1. Connect to vehicle (relay OFF)
2. Prepare vehicle state
3. Enable relay (apply load)
4. Execute IBIT test
5. Disable relay (remove load)
6. Restore vehicle state
7. Cleanup
"""
import os
import time
import threading
import csv
from collections import deque
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .callbacks import ExecutorCallbacks, PreparationCallbacks
from pymavlink import mavutil
from vehicle.connection import connect_to_vehicle
from vehicle.preparation import UUTPreparation
from vehicle.constants import (
    ActuationMode, IBITSubstate, FlightRegime, MsgType,
    IBIT_SUBSTATE_NAMES, IBIT_SUBSTATE_DISPLAY_NAMES, MISTRACKING_FLAG_NAMES,
    get_mode_name, get_flight_regime_name, get_failed_surfaces, is_armed,
    DEFAULT_IBIT_TIMEOUT, DEFAULT_PHASE_TIMEOUT, DEFAULT_HEARTBEAT_TIMEOUT,
    RELAY_DISABLE_MAX_ATTEMPTS, RELAY_DISABLE_RETRY_DELAY,
    MAX_CONSECUTIVE_TELEMETRY_ERRORS, OPERATE_WAIT_TIMEOUT,
    HEARTBEAT_BURST_INTERVAL,
)
from .logger import TelemetryLogger


def _build_actuator_feedback_dict(msg: Any) -> Dict[str, float]:
    """Build actuator feedback dict from a PANDION_RR_ACTUATION_SYS_STATUS message."""
    return {
        'left_elevon_feedback_cdeg': msg.left_elevon_feedback_cdeg,
        'right_elevon_feedback_cdeg': msg.right_elevon_feedback_cdeg,
        'dorsal_rudder_feedback_cdeg': msg.dorsal_rudder_feedback_cdeg,
        'ventral_rudder_feedback_cdeg': msg.ventral_rudder_feedback_cdeg,
        'left_tvc_upper_feedback_cdeg': msg.left_tvc_upper_feedback_cdeg,
        'left_tvc_lower_feedback_cdeg': msg.left_tvc_lower_feedback_cdeg,
        'right_tvc_upper_feedback_cdeg': msg.right_tvc_upper_feedback_cdeg,
        'right_tvc_lower_feedback_cdeg': msg.right_tvc_lower_feedback_cdeg,
        'left_elevon_current_mA': msg.left_elevon_current_mA,
        'right_elevon_current_mA': msg.right_elevon_current_mA,
        'dorsal_rudder_current_mA': msg.dorsal_rudder_current_mA,
        'ventral_rudder_current_mA': msg.ventral_rudder_current_mA,
        'left_tvc_upper_current_mA': msg.left_tvc_upper_current_mA,
        'left_tvc_lower_current_mA': msg.left_tvc_lower_current_mA,
        'right_tvc_upper_current_mA': msg.right_tvc_upper_current_mA,
        'right_tvc_lower_current_mA': msg.right_tvc_lower_current_mA,
        'left_elevon_motor_temp_degC': msg.left_elevon_motor_temp_degC,
        'right_elevon_motor_temp_degC': msg.right_elevon_motor_temp_degC,
    }


class IBITPhaseTracker:
    """
    Phase tracking for IBIT test sequence.
    
    IBIT Substates:
    0: BEGIN (initialization)
    1: WAIT_FOR_SETTLE (stabilization)
    2: ELEVONS (wing control test)
    3: RUDDERS (tail control test)
    4: TVC (engine gimbal test)
    5: COMPLETE (all tests passed)
    
    Note: Completion is detected by mode transition IBIT(1) → OPERATE(2),
    not by reaching substate 5 (vehicle may do multiple IBIT runs).
    """
    
    EXPECTED_SEQUENCE = [
        'WAIT_FOR_SETTLE',
        'ELEVONS',
        'RUDDERS',
        'TVC'
    ]

    EXPECTED_PHASES = EXPECTED_SEQUENCE  # Alias for external callers
    
    def __init__(self) -> None:
        """Initialize tracker"""
        self.phases_completed: List[str] = []
        self.last_substate: Optional[int] = None
        self.current_substate: Optional[int] = None
        self.phase_start_times: Dict[str, float] = {}
        self.phase_durations: Dict[str, float] = {}
        self.last_progress_time: float = time.time()
        self.reached_complete: bool = False
        self.transition_history: List[Dict[str, Any]] = []
    
    def update(self, substate: int) -> None:
        """
        Update tracker with current substate.
        
        Args:
            substate: Current IBIT substate (0-5)
        """
        if substate != self.last_substate:
            self.transition_history.append({
                'from': self.last_substate,
                'to': substate,
                'timestamp': time.time()
            })
            
            # Track phase transitions
            if substate == IBITSubstate.WAIT_FOR_SETTLE:
                self._start_phase('WAIT_FOR_SETTLE')
            elif substate == IBITSubstate.ELEVONS:
                self._complete_phase('WAIT_FOR_SETTLE')
                self._start_phase('ELEVONS')
            elif substate == IBITSubstate.RUDDERS:
                self._complete_phase('ELEVONS')
                self._start_phase('RUDDERS')
            elif substate == IBITSubstate.TVC:
                self._complete_phase('RUDDERS')
                self._start_phase('TVC')
            elif substate == IBITSubstate.COMPLETE:
                self._complete_phase('TVC')
                self.reached_complete = True
                self.last_progress_time = time.time()
            
            self.last_substate = substate
        
        self.current_substate = substate
    
    def _start_phase(self, phase_name: str) -> None:
        """Record phase start time"""
        if phase_name not in self.phase_start_times:
            self.phase_start_times[phase_name] = time.time()
            self.last_progress_time = time.time()
    
    def _complete_phase(self, phase_name: str) -> None:
        """Record phase completion"""
        if phase_name not in self.phases_completed:
            self.phases_completed.append(phase_name)
            
            if phase_name in self.phase_start_times:
                duration = time.time() - self.phase_start_times[phase_name]
                self.phase_durations[phase_name] = duration
            
            self.last_progress_time = time.time()
    
    def is_complete(self) -> bool:
        """Check if IBIT reached COMPLETE state (substate 5)"""
        return self.reached_complete and self.current_substate == IBITSubstate.COMPLETE
    
    def get_progress(self) -> float:
        """Get test progress (0.0 to 1.0)"""
        if self.reached_complete:
            return 1.0
        return len(self.phases_completed) / len(self.EXPECTED_SEQUENCE)
    
    def time_since_last_progress(self) -> float:
        """Time since last progress in seconds"""
        return time.time() - self.last_progress_time
    
    def get_current_phase_name(self) -> str:
        """Get name of current phase"""
        return IBIT_SUBSTATE_NAMES.get(self.current_substate, "UNKNOWN")
    
    def get_summary(self) -> Dict[str, Any]:
        """Get progress summary"""
        return {
            'current_phase': self.get_current_phase_name(),
            'current_substate': self.current_substate,
            'phases_completed': self.phases_completed,
            'reached_complete': self.reached_complete,
            'progress_percent': self.get_progress() * 100,
            'phase_durations': self.phase_durations.copy(),
            'transition_count': len(self.transition_history)
        }

    def __repr__(self) -> str:
        return (
            f"IBITPhaseTracker(phase={self.get_current_phase_name()}, "
            f"completed={self.phases_completed}, "
            f"complete={self.reached_complete})"
        )


class TestStatistics:
    """Tracks real-time test statistics"""
    
    def __init__(self) -> None:
        """Initialize statistics"""
        self.commands_sent = 0
        self.telemetry_received = 0
        self.heartbeats_received = 0
        self.last_heartbeat_time = 0
        self.communication_errors = 0
        self.iteration_times = deque(maxlen=20)
        self.telemetry_rate_history = deque(maxlen=60)
        self.start_time = time.time()
        self.last_telemetry_count = 0
        self.last_rate_update = time.time()
    
    def record_command_sent(self) -> None:
        """Record a command was sent"""
        self.commands_sent += 1
    
    def record_telemetry_received(self) -> None:
        """Record telemetry message received"""
        self.telemetry_received += 1
    
    def record_heartbeat(self) -> None:
        """Record heartbeat received"""
        self.heartbeats_received += 1
        self.last_heartbeat_time = time.time()
    
    def record_communication_error(self) -> None:
        """Record communication error"""
        self.communication_errors += 1
    
    def record_iteration_time(self, duration: float) -> None:
        """Record iteration completion time"""
        self.iteration_times.append(duration)
    
    def get_average_iteration_time(self) -> float:
        """Get average iteration time"""
        if not self.iteration_times:
            return 0.0
        return sum(self.iteration_times) / len(self.iteration_times)
    
    def update_telemetry_rate(self) -> None:
        """Update telemetry rate calculation"""
        now = time.time()
        if now - self.last_rate_update >= 1.0:
            rate = self.telemetry_received - self.last_telemetry_count
            self.telemetry_rate_history.append(rate)
            self.last_telemetry_count = self.telemetry_received
            self.last_rate_update = now
    
    def get_current_telemetry_rate(self) -> int:
        """Get current telemetry rate (messages/sec)"""
        if not self.telemetry_rate_history:
            return 0
        return self.telemetry_rate_history[-1]
    
    def get_average_telemetry_rate(self) -> float:
        """Get average telemetry rate"""
        if not self.telemetry_rate_history:
            return 0
        return sum(self.telemetry_rate_history) / len(self.telemetry_rate_history)
    
    def time_since_last_heartbeat(self) -> float:
        """Time since last heartbeat in seconds"""
        if self.last_heartbeat_time == 0:
            return float('inf')
        return time.time() - self.last_heartbeat_time
    
    def is_connection_healthy(self) -> bool:
        """Check if connection is healthy"""
        return self.time_since_last_heartbeat() < DEFAULT_HEARTBEAT_TIMEOUT


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
        self.preparation = UUTPreparation(
            self.master, self.config, self.telemetry_logger, callbacks=prep_cb
        )

    def _enable_relay(self, label: str = "test") -> None:
        """Enable the load relay with stabilization and heartbeat check."""
        self.cb.on_status(f"Enabling load relay for {label}...")
        self.cb.on_log("\n" + "=" * 60)
        self.cb.on_log("ENABLING LOAD RELAY")
        self.cb.on_log("=" * 60)

        ok, msg = self.daq.set_line(self.uut.relay_line, True)
        if not ok:
            raise Exception(f"Failed to enable relay: {msg}")
        if self.telemetry_logger:
            self.telemetry_logger.log_relay_state(self.uut.relay_line, True)

        self.cb.on_log(
            f"\u2713 Relay {self.uut.relay_line} ENABLED - Load applied"
        )
        self.cb.on_log(
            f"  Waiting {self.stabilization_delay}s for stabilization..."
        )
        time.sleep(self.stabilization_delay)

        hb = self.master.wait_heartbeat(timeout=2.0)
        if not hb:
            raise Exception("Lost connection after applying load")
        self.cb.on_log("\u2713 Vehicle responsive under load")
        self.cb.on_log("=" * 60 + "\n")

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
            except Exception as e:
                self.cb.on_log(f"\u26a0 Heartbeat send error: {e}")
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
                ok, msg = self.daq.set_line(self.uut.relay_line, False)
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
                    self.cb.on_log(
                        "\u2713 Emergency relay disable SUCCESSFUL"
                    )
                    self.cb.on_log("=" * 60)
                    return
                else:
                    self.cb.on_log(
                        f"  \u2717 Attempt {attempt} failed: {msg}"
                    )
            except Exception as err:
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

    def _wait_for_message(self, msg_type: str, timeout: float = 5.0) -> Optional[Any]:
        """Thread-safe MAVLink recv_match wrapper."""
        with self.master_lock:
            return self.master.recv_match(
                type=msg_type, blocking=True, timeout=timeout
            )

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


# ════════════════════════════════════════════════════════════════════════════════
# IBIT Test Executor
# ════════════════════════════════════════════════════════════════════════════════

class UUTTestExecutor(_ExecutorMixin, threading.Thread):
    """
    Executes IBIT test with complete event logging.

    Runs in separate thread to avoid blocking UI.
    Invokes callbacks for UI updates.
    """

    def __init__(self, uut, daq_controller, batch_end_time,
                 stabilization_delay, connection_timeout,
                 log_directory, test_start_datetime,
                 skip_state_management=False, config=None, callbacks=None):
        threading.Thread.__init__(self, daemon=True)
        self._init_executor(
            uut, daq_controller, batch_end_time,
            stabilization_delay, connection_timeout,
            log_directory, test_start_datetime, config,
        )
        self.cb = callbacks or ExecutorCallbacks()
        self.skip_state_management = skip_state_management
        self.statistics = TestStatistics()
        self.phase_tracker = IBITPhaseTracker()
        self.current_ibit_substate = None
    
    def run(self):
        """Execute IBIT test with full state management and logging."""
        self.running = True
        success = False
        message = ""
        
        try:
            if time.time() >= self.batch_end_time:
                self.cb.on_time_expired()
                return
            
            # Connect and start heartbeat (shared)
            self._connect_and_start_heartbeat()
            
            # Initialize telemetry logger (shared)
            self._open_telemetry_logger(test_mode='ibit')
            
            # Increment iteration and log
            self.uut.iterations_completed += 1
            self.telemetry_logger.set_iteration_number(self.uut.iterations_completed)
            self.telemetry_logger.log_test_event(
                'ITERATION_START',
                f"Starting IBIT test iteration #{self.uut.iterations_completed} "
                f"for UUT {self.uut.serial_number}"
            )
            
            # State management (if not skipped)
            if not self.skip_state_management:
                self.cb.on_log(
                    "\u2192 Beginning state capture (GCS heartbeats active)..."
                )
                self._create_preparation()
                
                prep_ok, prep_msg = self.preparation.capture_initial_state()
                if not prep_ok:
                    raise Exception(prep_msg)
                
                prep_ok, prep_msg = self.preparation.prepare_for_test()
                if not prep_ok:
                    raise Exception(prep_msg)
            else:
                self.cb.on_log("\u26a0 Skipping state management (as configured)")
                self.cb.on_log("\u2192 Requesting IBIT mode (mode 1)")
                self.telemetry_logger.log_test_event(
                    'IBIT_REQUEST',
                    'Requesting IBIT mode (skipped state management)'
                )
                with self.master_lock:
                    self.master.mav.pandion_rr_actuation_request_mode_send(
                        requested_mode=ActuationMode.IBIT
                    )
                time.sleep(1.0)
            
            # Enable relay (shared)
            self._enable_relay(label="IBIT test")
            
            # Execute IBIT test
            self.execute_ibit_test()
            
            success = True
            message = f"IBIT test complete (Iteration {self.uut.iterations_completed})"
            
        except Exception as e:
            success = False
            message = f"Test failed: {str(e)}"
            self.cb.on_log(f"\u2717 Error: {e}")
            self.cb.on_alert(f"TEST FAILED: {str(e)}")
            
            if self.daq:
                self._emergency_relay_disable()
            
            if self.telemetry_logger:
                self.telemetry_logger.log_test_event(
                    'TEST_FAILED', f'Test failed: {str(e)}'
                )
        
        finally:
            self.cleanup()
        
        self.cb.on_complete(success, message)
    
    def execute_ibit_test(self):
        """Execute IBIT test - wait for COMPLETE state then return to OPERATE."""
        self._start_background_workers()
        self.cb.on_iteration(self.uut.iterations_completed)
        test_start = time.time()
        self.uut.test_start_time = test_start
        self.cb.on_status(
            f"Running IBIT (Iteration {self.uut.iterations_completed})..."
        )
        self.cb.on_log("="*60)
        self.cb.on_log("STARTING IBIT TEST SEQUENCE")
        self.cb.on_log("="*60)
        self.cb.on_log("Expected sequence:")
        self.cb.on_log(
            "  0: BEGIN → 1: WAIT_FOR_SETTLE → 2: ELEVONS → "
            "3: RUDDERS → 4: TVC → 5: COMPLETE"
        )
        self.cb.on_log("Heartbeat running in background at 1 Hz")
        self.cb.on_log("")

        self._ibit_monitor_loop()

        if time.time() >= self.batch_end_time:
            self.cb.on_log("Batch time expired during IBIT")
            return
        if not self.phase_tracker.reached_complete:
            raise Exception(
                f"IBIT did not reach COMPLETE state "
                f"(stuck at substate {self.phase_tracker.current_substate})"
            )

        self._wait_for_operate_after_ibit()
        self._log_ibit_summary(test_start)

    # ── IBIT sub-methods ────────────────────────────────────────────────

    def _start_background_workers(self):
        """Spawn telemetry, stats, health, log-size, and duration worker threads."""
        for target in (
            self._receive_telemetry_worker,
            self._statistics_update_worker,
            self._connection_health_monitor,
            self._log_size_monitor,
            self._test_duration_monitor,
        ):
            threading.Thread(target=target, daemon=True).start()

    def _ibit_monitor_loop(self):
        """Run the main IBIT monitoring loop until completion, timeout, or batch expiry."""
        ibit_timeout = self.config.get('ibit_timeout', DEFAULT_IBIT_TIMEOUT)
        phase_timeout = self.config.get('phase_timeout', DEFAULT_PHASE_TIMEOUT)

        ibit_start_time = time.time()
        last_logged_phase = None

        # Initialize mode tracking
        self._last_mode = None
        self._ibit_run_count = 0
        self._last_substate = None

        # Accumulate mistracking flags across ALL IBIT messages.
        # The firmware zeros actuation_ibit_mon_status as soon as it leaves
        # IBIT mode, so reading it from the first OPERATE message always
        # yields 0x00.  We OR-accumulate while still in IBIT to capture
        # any transient fault flags.
        self._accumulated_mistracking = 0

        while self.running and time.time() < self.batch_end_time:
            # Check timeouts
            if time.time() - ibit_start_time > ibit_timeout:
                raise Exception(f"IBIT timeout after {ibit_timeout}s")

            if self.phase_tracker.time_since_last_progress() > phase_timeout:
                current_phase = self.phase_tracker.get_current_phase_name()
                raise Exception(
                    f"Phase timeout at {current_phase} after {phase_timeout}s"
                )

            # Check IBIT status
            status_msg = self._wait_for_message(
                MsgType.ACTUATION_SYS_STATUS,
                timeout=0.1
            )

            if status_msg:
                current_mode = status_msg.actuation_state
                current_substate = getattr(status_msg, 'actuation_ibit_substate', -1)

                # Initialize on first iteration
                if self._last_mode is None:
                    self._last_mode = current_mode
                    self._last_substate = current_substate

                # Detect IBIT run restarts (TVC → BEGIN/SETTLE)
                if self._last_mode == ActuationMode.IBIT and current_mode == ActuationMode.IBIT:
                    if self._last_substate in (IBITSubstate.RUDDERS, IBITSubstate.TVC) and current_substate in (IBITSubstate.BEGIN, IBITSubstate.WAIT_FOR_SETTLE):
                        self._ibit_run_count += 1
                        self.cb.on_log(
                            f"\n→ IBIT Run #{self._ibit_run_count + 1} detected "
                            f"(vehicle performing multiple cycles)"
                        )

                # CRITICAL: IBIT completion detected by mode transition IBIT → OPERATE
                if self._last_mode == ActuationMode.IBIT and current_mode == ActuationMode.OPERATE:
                    self._handle_ibit_completion(status_msg, current_substate)
                    break

                elif current_mode == ActuationMode.OFF:  # Transitioned to OFF
                    raise Exception(
                        f"IBIT aborted - vehicle transitioned to OFF mode "
                        f"(substate: {current_substate})"
                    )

                elif self._last_mode == ActuationMode.IBIT and current_mode not in (ActuationMode.IBIT, ActuationMode.OPERATE):
                    # Unexpected mode
                    mode_str = get_mode_name(current_mode)
                    raise Exception(
                        f"Unexpected mode transition during IBIT: IBIT → {mode_str}"
                    )

                # Still in IBIT mode - continue tracking substates
                if current_mode == ActuationMode.IBIT:
                    # Accumulate mistracking flags while in IBIT.
                    # Firmware zeros this field on mode exit, so we must
                    # capture it every message while still in IBIT.
                    ibit_mon = getattr(status_msg, 'actuation_ibit_mon_status', 0)
                    self._accumulated_mistracking |= ibit_mon

                    last_logged_phase = self._track_ibit_substate(
                        status_msg, last_logged_phase
                    )

                # Update tracking variables
                self._last_mode = current_mode
                self._last_substate = current_substate

            time.sleep(0.01)

    def _handle_ibit_completion(self, status_msg, current_substate):
        """Evaluate mistracking, log result, mark tracker complete, and disable relay."""
        # Use accumulated mistracking flags from all IBIT-mode messages.
        # The firmware zeros actuation_ibit_mon_status on the IBIT→OPERATE
        # transition, so reading from status_msg here would always be 0x00.
        mistracking = self._accumulated_mistracking
        failed_surfaces = get_failed_surfaces(mistracking)

        total_runs = self._ibit_run_count + 1
        self.cb.on_log(
            f"\n{'✓' if not failed_surfaces else '✗'} IBIT completed "
            f"after {total_runs} run(s) — "
            f"Mode: IBIT(1) → OPERATE(2)"
        )

        if failed_surfaces:
            self.cb.on_log(
                f"  ✗ IBIT FAIL — mistracking on: "
                f"{', '.join(failed_surfaces)} "
                f"(flags=0x{mistracking:02X})"
            )
            if self.telemetry_logger:
                self.telemetry_logger.log_test_event(
                    'IBIT_FAIL',
                    f'Mistracking detected on: '
                    f'{", ".join(failed_surfaces)} '
                    f'(flags=0x{mistracking:02X})'
                )
            raise Exception(
                f"IBIT FAIL — mistracking on: "
                f"{', '.join(failed_surfaces)}"
            )
        else:
            self.cb.on_log(
                f"  ✓ IBIT PASS — no mistracking flags set"
            )
            if self.telemetry_logger:
                self.telemetry_logger.log_test_event(
                    'IBIT_PASS',
                    'IBIT passed — all surfaces tracked correctly'
                )
        self.cb.on_log(f"  Final IBIT substate: {current_substate}")
        self.cb.on_log("")
        self.cb.on_log("="*60)
        self.cb.on_log("✓ IBIT PASS — Vehicle ready for flight!")
        self.cb.on_log("="*60)

        # Mark tracker as complete
        self.phase_tracker.reached_complete = True

        # Ensure all phases are marked complete
        for phase in IBITPhaseTracker.EXPECTED_PHASES:
            if phase not in self.phase_tracker.phases_completed:
                self.phase_tracker.phases_completed.append(phase)

        self._log_phase_summary(total_runs)
        self._disable_relay_after_ibit()

    def _track_ibit_substate(self, status_msg, last_logged_phase):
        """Track IBIT substate transitions and update the GUI. Returns updated last_logged_phase."""
        if hasattr(status_msg, 'actuation_ibit_substate'):
            substate = status_msg.actuation_ibit_substate
            self.phase_tracker.update(substate)
            current_phase = self.phase_tracker.get_current_phase_name()

            # Log phase transitions
            if current_phase != last_logged_phase:
                self.cb.on_log(
                    f"→ Substate {substate}: {current_phase}"
                )
                last_logged_phase = current_phase

            # Update GUI display
            display_name = IBIT_SUBSTATE_DISPLAY_NAMES.get(
                substate,
                f"UNKNOWN({substate})"
            )
            self.cb.on_ibit_state(display_name)
        return last_logged_phase

    def _log_phase_summary(self, total_runs):
        """Log phase duration summary after IBIT completion."""
        self.cb.on_log(
            f"Phases observed: {len(self.phase_tracker.phases_completed)}/4"
        )
        for phase in self.phase_tracker.phases_completed:
            duration = self.phase_tracker.phase_durations.get(phase, 0)
            if duration > 0:
                self.cb.on_log(
                    f"  ✓ {phase:20s} - {duration:.2f}s"
                )
            else:
                self.cb.on_log(f"  ✓ {phase:20s} - completed")

        if total_runs > 1:
            self.cb.on_log(
                f"\nℹ️  Vehicle performed {total_runs} IBIT cycles "
                f"(firmware-controlled)"
            )

    def _disable_relay_after_ibit(self):
        """Disable the load relay after successful IBIT completion."""
        self.cb.on_log("\n" + "="*60)
        self.cb.on_log("IBIT COMPLETE - DISABLING LOAD RELAY")
        self.cb.on_log("="*60)
        self.cb.on_log(
            "✓ IBIT sequence finished - removing load from vehicle"
        )

        success_relay, msg = self.daq.set_line(self.uut.relay_line, False)
        if success_relay:
            if self.telemetry_logger:
                self.telemetry_logger.log_relay_state(
                    self.uut.relay_line,
                    False
                )
            self.cb.on_log(
                f"✓ Relay {self.uut.relay_line} DISABLED - Load removed"
            )
        else:
            self.cb.on_log(f"⚠ Relay disable warning: {msg}")

        self.cb.on_log("="*60 + "\n")

    def _wait_for_operate_after_ibit(self):
        """Wait for the vehicle to return to OPERATE mode after IBIT completion."""
        self.cb.on_log("\n→ Waiting for vehicle to return to OPERATE mode...")
        self.cb.on_status("Waiting for OPERATE mode...")

        operate_timeout = OPERATE_WAIT_TIMEOUT
        operate_start = time.time()
        returned_to_operate = False

        while time.time() - operate_start < operate_timeout:
            mode_msg = self._wait_for_message(
                MsgType.ACTUATION_SYS_STATUS,
                timeout=1.0
            )

            if mode_msg:
                current_mode = mode_msg.actuation_state

                if current_mode == ActuationMode.OPERATE:
                    returned_to_operate = True
                    self.cb.on_log(f"  ✓ Vehicle returned to OPERATE mode")
                    break
                elif current_mode == ActuationMode.IBIT:
                    pass  # Still transitioning
                else:
                    self.cb.on_log(
                        f"  ⚠ Unexpected mode: {current_mode} "
                        f"({get_mode_name(current_mode)})"
                    )

            time.sleep(0.5)

        if not returned_to_operate:
            final_mode_msg = self._wait_for_message(
                MsgType.ACTUATION_SYS_STATUS,
                timeout=2.0
            )
            final_mode = final_mode_msg.actuation_state if final_mode_msg else -1
            self.cb.on_log(
                f"  ⚠ Vehicle did not return to OPERATE within {operate_timeout}s"
            )
            self.cb.on_log(
                f"  Final mode: {final_mode} "
                f"({get_mode_name(final_mode)})"
            )
            self.cb.on_log(f"  → Proceeding with cleanup anyway...")

    def _log_ibit_summary(self, test_start):
        """Record metrics and log final IBIT summary."""
        self.uut.test_end_time = time.time()
        test_duration = self.uut.test_end_time - test_start
        self.statistics.record_iteration_time(test_duration)

        self.telemetry_logger.log_test_event(
            'ITERATION_COMPLETE',
            f"IBIT test iteration #{self.uut.iterations_completed} completed "
            f"successfully for UUT {self.uut.serial_number} - "
            f"Duration: {test_duration:.1f} seconds"
        )

        self.cb.on_log(
            f"\n✓ IBIT test completed successfully in {test_duration:.1f}s"
        )
        self.cb.on_log(
            f"  Total transitions: {len(self.phase_tracker.transition_history)}"
        )
        self.cb.on_log(f"  Sequence: IBIT → COMPLETE → OPERATE ✓")

    def cleanup(self):
        """
        Cleanup after test completion or failure.
        
        Relay is already disabled in execute_ibit_test() or exception handler.
        """
        self.cb.on_log(
            "\u2192 Beginning cleanup (relay already OFF, restoring vehicle state)..."
        )
        time.sleep(1.0)
        
        if not self.running:
            # Quick cleanup path
            self.running = False
            self._stop_heartbeat()
            self._close_resources()
            self.cb.on_log("Quick cleanup complete (relay already OFF)")
            return
        
        # Normal cleanup path — restore state
        if self.master and self.preparation and self.preparation.initial_state.captured:
            self.preparation.restore_original_state()
            
            if not self.running:
                self.cb.on_log(
                    "\u26a0 Stop requested during restoration - aborting..."
                )
                self._stop_heartbeat()
                self._close_resources()
                return
            
            time.sleep(2.0)
            self.preparation.verify_final_state(relay_was_disabled=True)
        
        self.cb.on_log("\u2192 Stopping heartbeat sender...")
        self._stop_heartbeat()
        self._close_resources()
        self.cb.on_log("Cleanup complete - ready for next iteration")
    
    def _receive_telemetry_worker(self):
        """Enhanced telemetry receiver with thread-safe message reception"""
        consecutive_errors = 0
        max_consecutive_errors = MAX_CONSECUTIVE_TELEMETRY_ERRORS
        
        while self.running:
            try:
                # CRITICAL: Use lock for recv_match to prevent concurrent access
                with self.master_lock:
                    msg = self.master.recv_match(blocking=False, timeout=0.1)
                
                if msg:
                    consecutive_errors = 0
                    
                    # Log telemetry
                    if self.telemetry_logger:
                        self.telemetry_logger.log_telemetry(msg)
                    
                    self.statistics.record_telemetry_received()
                    
                    # Handle specific message types
                    msg_type = msg.get_type()
                    
                    # Armed state from PANDION_STATUS
                    if msg_type == MsgType.PANDION_STATUS:
                        flight_regime = msg.flight_regime
                        armed = is_armed(flight_regime)
                        self.cb.on_armed_state(armed, flight_regime)
                    
                    # Heartbeat
                    if msg_type == MsgType.HEARTBEAT:
                        self.statistics.record_heartbeat()
                    
                    # Mode from actuation status
                    if msg_type == MsgType.ACTUATION_SYS_STATUS:
                        mode = msg.actuation_state
                        self.cb.on_mode(mode)
                        
                        if hasattr(msg, 'actuation_ibit_substate'):
                            self.current_ibit_substate = msg.actuation_ibit_substate
                        
                        # Actuator feedback
                        try:
                            actuator_data = _build_actuator_feedback_dict(msg)
                            self.cb.on_actuator_feedback(actuator_data)
                        except AttributeError:
                            pass
                
            except Exception as e:
                consecutive_errors += 1
                if consecutive_errors >= max_consecutive_errors:
                    self.cb.on_log(f"⚠ Multiple telemetry errors: {e}")
                    self.cb.on_alert(f"Telemetry reception issues")
                    consecutive_errors = 0
                self.statistics.record_communication_error()
    
    def _statistics_update_worker(self):
        """Periodically update statistics"""
        while self.running:
            time.sleep(1.0)
            self.statistics.update_telemetry_rate()
            self.cb.on_statistics(self.statistics)
    
    def _connection_health_monitor(self):
        """Monitor connection health"""
        last_warning_time = 0
        
        while self.running:
            time.sleep(0.5)
            is_healthy = self.statistics.is_connection_healthy()
            self.cb.on_connection_health(is_healthy)
            
            if not is_healthy:
                now = time.time()
                if now - last_warning_time > 5.0:
                    time_since = self.statistics.time_since_last_heartbeat()
                    self.cb.on_alert(f"No heartbeat for {time_since:.1f}s")
                    self.cb.on_log(
                        f"⚠ Connection unhealthy - no heartbeat for {time_since:.1f}s"
                    )
                    last_warning_time = now
    
    def _log_size_monitor(self):
        """Monitor log file size"""
        while self.running:
            time.sleep(5.0)
            if self.telemetry_logger and self.uut.log_file:
                try:
                    if os.path.exists(self.uut.log_file):
                        file_size = os.path.getsize(self.uut.log_file)
                        size_mb = file_size / (1024 * 1024)
                        self.cb.on_log_file_size(size_mb)
                except Exception:
                    pass
    
    def _test_duration_monitor(self):
        """Monitor test duration"""
        while self.running:
            time.sleep(1.0)
            if self.uut.test_start_time:
                duration = time.time() - self.uut.test_start_time
                self.cb.on_test_duration(duration)
    


class IBITFailureDiagnostic:
    """Structured IBIT failure diagnostics"""
    
    def __init__(self) -> None:
        self.failed_phase = None
        self.phases_completed = []
        self.monitor_status = None
        self.recent_errors = deque(maxlen=20)
        self.vehicle_state = None
        self.arm_attempts = 0
        self.failure_time = None
        self.failure_reason = None
    
    def record_phase_complete(self, phase_name: str) -> None:
        """Record that a phase completed"""
        if phase_name not in self.phases_completed:
            self.phases_completed.append(phase_name)
    
    def record_error(self, severity: str, message: str) -> None:
        """Record an error message"""
        self.recent_errors.append({
            'timestamp': time.time(),
            'severity': severity,
            'message': message
        })
    
    def set_failure_info(self, phase: str, reason: str) -> None:
        """Set failure information"""
        self.failed_phase = phase
        self.failure_reason = reason
        self.failure_time = time.time()
    
    def generate_report(self) -> Dict[str, Any]:
        """Generate comprehensive failure report"""
        return {
            'failure_time': datetime.fromtimestamp(self.failure_time).strftime('%Y-%m-%d %H:%M:%S') if self.failure_time else None,
            'failed_phase': self.failed_phase,
            'failure_reason': self.failure_reason,
            'phases_completed': self.phases_completed,
            'test_progress': f"{len(self.phases_completed)}/4 phases",
            'arm_attempts': self.arm_attempts,
            'monitor_status': self.monitor_status,
            'recent_errors': list(self.recent_errors),
            'vehicle_state': self.vehicle_state,
            'recommended_action': self.get_recommendation()
        }
    
    def get_recommendation(self) -> str:
        """Get recommended action based on failure"""
        if not self.failure_reason:
            return "Unknown failure - check logs"
        
        if 'ARM' in self.failure_reason.upper():
            if self.monitor_status and len(self.monitor_status.get('set_monitors', [])) > 0:
                return "ARM failed due to SET monitors - investigate monitor conditions"
            return "ARM failed - check vehicle health and safety conditions"
        
        if 'TIMEOUT' in self.failure_reason.upper():
            if len(self.phases_completed) == 0:
                return "Test never started - check IBIT initialization"
            return f"Test stalled at {self.failed_phase} - check actuator hardware"
        
        if 'MONITOR' in self.failure_reason.upper():
            return "Monitor issues - verify override functionality and clear all monitors"
        
        return "Review diagnostics and try again"
    
    def format_display(self) -> str:
        """Format diagnostics for console display"""
        lines = []
        lines.append("=" * 60)
        lines.append("⚠⚠⚠ IBIT FAILURE DIAGNOSTICS ⚠⚠⚠")
        lines.append("=" * 60)
        
        if self.failure_time:
            lines.append(f"Failure Time: {datetime.fromtimestamp(self.failure_time).strftime('%H:%M:%S')}")
        
        lines.append(f"Failed Phase: {self.failed_phase or 'Unknown'}")
        lines.append(f"Reason: {self.failure_reason or 'Unknown'}")
        lines.append("")
        
        lines.append("Test Progress:")
        phases = ['WAIT_FOR_SETTLE', 'ELEVONS', 'RUDDERS', 'TVC']
        for phase in phases:
            status = '✓' if phase in self.phases_completed else '✗'
            lines.append(f"  {status} {phase}")
        lines.append(f"  Progress: {len(self.phases_completed)}/4 phases")
        lines.append("")
        
        if self.arm_attempts > 0:
            lines.append(f"ARM Attempts: {self.arm_attempts}")
        
        if self.monitor_status:
            set_monitors = self.monitor_status.get('set_monitors', [])
            lines.append(f"SET Monitors: {len(set_monitors)}")
            if set_monitors:
                lines.append(f"  IDs: {set_monitors}")
        
        if self.recent_errors:
            lines.append("\nRecent Errors:")
            for error in list(self.recent_errors)[-5:]:
                lines.append(f"  [{error['severity']}] {error['message']}")
        
        lines.append("\nRecommended Action:")
        lines.append(f"  {self.get_recommendation()}")
        lines.append("=" * 60)
        
        return "\n".join(lines)


# ============================================================
# Flight Profile Playback Executor
# ============================================================

class PlaybackTestExecutor(_ExecutorMixin, threading.Thread):
    """
    Executes a flight profile playback test.

    Sequence:
      1. Connect to vehicle
      2. Set CLASSIC_MODE_EN=1, USE_NEST=0, power cycle
      3. ARM -> OPERATE -> PLAYBACK
      4. Stream PANDION_RR_PLAYBACK_COMMAND at 100 Hz from CSV
      5. Log command vs feedback delta per surface per frame
      6. Evaluate pass/fail against mistracking flags
      7. Restore vehicle state (CLASSIC_MODE_EN=0, power cycle)
    """

    # Playback type constants
    TYPE_ACTUATION  = 'Actuation'
    TYPE_PROPULSION = 'Propulsion'
    TYPE_BOTH       = 'Both'

    def __init__(self, uut, daq_controller, batch_end_time,
                 stabilization_delay, connection_timeout,
                 log_directory, test_start_datetime,
                 playback_csv, playback_type,
                 config=None, callbacks=None):
        threading.Thread.__init__(self, daemon=True)
        self._init_executor(
            uut, daq_controller, batch_end_time,
            stabilization_delay, connection_timeout,
            log_directory, test_start_datetime, config,
        )
        self.cb = callbacks or ExecutorCallbacks()
        self.playback_csv = playback_csv
        self.playback_type = playback_type

    # ----------------------------------------------------------
    # Thread entry point
    # ----------------------------------------------------------

    def run(self):
        self.running = True
        success = False
        message = ""

        try:
            if time.time() >= self.batch_end_time:
                self.cb.on_time_expired()
                return

            # Load CSV profile first so we fail fast before touching hardware
            profile = self._load_profile(self.playback_csv)
            self.cb.on_log(
                f"\u2713 Profile loaded: {len(profile)} frames "
                f"({len(profile) / 100.0:.1f}s at 100 Hz)"
            )

            # Connect and start heartbeat (shared)
            self._connect_and_start_heartbeat()

            # Telemetry logger (shared)
            self._open_telemetry_logger(test_mode='playback')

            self.uut.iterations_completed += 1
            self.telemetry_logger.set_iteration_number(self.uut.iterations_completed)
            self.telemetry_logger.log_test_event(
                'PLAYBACK_START',
                f"Starting playback test iteration #{self.uut.iterations_completed} "
                f"for UUT {self.uut.serial_number} \u2014 type={self.playback_type}"
            )

            # Preparation (shared helper)
            self._create_preparation()

            prep_ok, prep_msg = self.preparation.capture_initial_state()
            if not prep_ok:
                raise Exception(prep_msg)

            prep_ok, prep_msg = self.preparation.prepare_for_playback(
                self._power_cycle
            )
            if not prep_ok:
                raise Exception(prep_msg)

            # Enable load relay (shared)
            self._enable_relay(label="playback test")

            # Stream profile
            mistracking_flags, max_delta = self._stream_profile(profile)

            # Disable relay
            self.daq.set_line(self.uut.relay_line, False)
            self.telemetry_logger.log_relay_state(self.uut.relay_line, False)
            self.cb.on_log(f"\u2713 Relay {self.uut.relay_line} DISABLED")

            # Evaluate pass/fail
            success, message = self._evaluate_result(mistracking_flags, max_delta)

        except Exception as e:
            success = False
            message = f"Playback test failed: {str(e)}"
            self.cb.on_log(f"\u2717 Error: {e}")
            self.cb.on_alert(f"PLAYBACK FAILED: {str(e)}")
            if self.daq:
                self._emergency_relay_disable()
            if self.telemetry_logger:
                self.telemetry_logger.log_test_event('TEST_FAILED', str(e))

        finally:
            self._cleanup()

        self.cb.on_complete(success, message)

    # ----------------------------------------------------------
    # Profile loading
    # ----------------------------------------------------------

    def _load_profile(self, csv_path):
        """
        Load flight profile CSV and validate columns.

        Expected columns (in any order):
          timestamp
          event/left_elevon_ted_command_cdeg
          event/right_elevon_ted_command_cdeg
          event/lower_rudder_tel_command_cdeg
          event/upper_rudder_tel_command_cdeg
          event/left_tvc_upper_command_cdeg
          event/left_tvc_lower_command_cdeg
          event/right_tvc_upper_command_cdeg
          event/right_tvc_lower_command_cdeg
          event/left_engine_speed_command_prct_rpm
          event/right_engine_speed_command_prct_rpm

        Returns:
            List of dicts, one per 100 Hz frame.
        """
        required_cols = [
            'timestamp',
            'event/left_elevon_ted_command_cdeg',
            'event/right_elevon_ted_command_cdeg',
            'event/lower_rudder_tel_command_cdeg',
            'event/upper_rudder_tel_command_cdeg',
            'event/left_tvc_upper_command_cdeg',
            'event/left_tvc_lower_command_cdeg',
            'event/right_tvc_upper_command_cdeg',
            'event/right_tvc_lower_command_cdeg',
            'event/left_engine_speed_command_prct_rpm',
            'event/right_engine_speed_command_prct_rpm',
        ]

        with open(csv_path, newline='') as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                raise ValueError("CSV has no header row")
            missing = [c for c in required_cols if c not in reader.fieldnames]
            if missing:
                raise ValueError(f"CSV missing required columns: {missing}")
            rows = list(reader)

        if not rows:
            raise ValueError("CSV profile is empty")

        self.cb.on_log(f"  CSV columns: {list(rows[0].keys())}")
        return rows

    # ----------------------------------------------------------
    # Profile streaming — helpers
    # ----------------------------------------------------------

    def _send_playback_frame(self, frame):
        """Send a single PANDION_RR_PLAYBACK_COMMAND from a profile frame.

        Args:
            frame: dict with keys matching the playback command fields:
                left_elev, right_elev, low_rud, up_rud,
                l_tvc_up, l_tvc_lo, r_tvc_up, r_tvc_lo,
                l_eng, r_eng.
        """
        with self.master_lock:
            self.master.mav.pandion_rr_playback_command_send(
                left_elevon_ted_command_cdeg=frame['left_elev'],
                right_elevon_ted_command_cdeg=frame['right_elev'],
                lower_rudder_tel_command_cdeg=frame['low_rud'],
                upper_rudder_tel_command_cdeg=frame['up_rud'],
                left_tvc_upper_command_cdeg=frame['l_tvc_up'],
                left_tvc_lower_command_cdeg=frame['l_tvc_lo'],
                right_tvc_upper_command_cdeg=frame['r_tvc_up'],
                right_tvc_lower_command_cdeg=frame['r_tvc_lo'],
                left_engine_speed_command_prct_thrust=frame['l_eng'],
                right_engine_speed_command_prct_thrust=frame['r_eng'],
            )

    def _compute_frame_deltas(self, frame, feedback_msg):
        """Compute command-vs-feedback deltas for all surfaces.

        Args:
            frame: dict with parsed command values (same keys as _send_playback_frame).
            feedback_msg: PANDION_RR_ACTUATION_SYS_STATUS MAVLink message.

        Returns:
            dict mapping surface name to absolute delta in cdeg.
        """
        return {
            'left_elevon':    abs(frame['left_elev']  - getattr(feedback_msg, 'left_elevon_feedback_cdeg',  frame['left_elev'])),
            'right_elevon':   abs(frame['right_elev'] - getattr(feedback_msg, 'right_elevon_feedback_cdeg', frame['right_elev'])),
            'dorsal_rudder':  abs(frame['up_rud']     - getattr(feedback_msg, 'dorsal_rudder_feedback_cdeg',  frame['up_rud'])),
            'ventral_rudder': abs(frame['low_rud']    - getattr(feedback_msg, 'ventral_rudder_feedback_cdeg', frame['low_rud'])),
            'left_tvc_upper': abs(frame['l_tvc_up']   - getattr(feedback_msg, 'left_tvc_upper_feedback_cdeg', frame['l_tvc_up'])),
            'left_tvc_lower': abs(frame['l_tvc_lo']   - getattr(feedback_msg, 'left_tvc_lower_feedback_cdeg', frame['l_tvc_lo'])),
            'right_tvc_upper':abs(frame['r_tvc_up']   - getattr(feedback_msg, 'right_tvc_upper_feedback_cdeg', frame['r_tvc_up'])),
            'right_tvc_lower':abs(frame['r_tvc_lo']   - getattr(feedback_msg, 'right_tvc_lower_feedback_cdeg', frame['r_tvc_lo'])),
        }

    def _update_tracking(self, deltas, max_deltas, feedback_msg):
        """Update max_deltas and return accumulated mistracking flags from feedback.

        Args:
            deltas: dict of per-surface absolute deltas (from _compute_frame_deltas).
            max_deltas: running max-delta dict to update **in-place**.
            feedback_msg: PANDION_RR_ACTUATION_SYS_STATUS MAVLink message.

        Returns:
            int — mistracking flag bits from this feedback message.
        """
        for surface, delta in deltas.items():
            if delta > max_deltas[surface]:
                max_deltas[surface] = delta

        return getattr(feedback_msg, 'actuation_ibit_mon_status', 0)

    # ----------------------------------------------------------
    # Profile streaming — main loop
    # ----------------------------------------------------------

    def _stream_profile(self, profile):
        """
        Stream PANDION_RR_PLAYBACK_COMMAND at 100 Hz and collect feedback.

        Returns:
            (mistracking_flags: int, max_deltas: dict surface->max_cdeg_error)
        """
        self.cb.on_log("=" * 60)
        self.cb.on_log("STREAMING FLIGHT PROFILE")
        self.cb.on_log(f"  Type: {self.playback_type}")
        self.cb.on_log(f"  Frames: {len(profile)}")
        self.cb.on_log("=" * 60)

        self.uut.test_start_time = time.time()
        interval = 1.0 / 100.0  # 100 Hz

        # Accumulated mistracking flags (OR across all frames)
        accumulated_flags = 0
        max_deltas = {
            'left_elevon': 0.0,
            'right_elevon': 0.0,
            'dorsal_rudder': 0.0,
            'ventral_rudder': 0.0,
            'left_tvc_upper': 0.0,
            'left_tvc_lower': 0.0,
            'right_tvc_upper': 0.0,
            'right_tvc_lower': 0.0,
        }

        use_actuation = self.playback_type in (self.TYPE_ACTUATION, self.TYPE_BOTH)
        use_propulsion = self.playback_type in (self.TYPE_PROPULSION, self.TYPE_BOTH)

        total_frames = len(profile)
        last_pct_logged = -1

        for frame_idx, row in enumerate(profile):
            if not self.running:
                self.cb.on_log("⚠ Playback stopped by user")
                break

            frame_start = time.time()

            # Parse commands
            try:
                cmds = {
                    'left_elev':  float(row['event/left_elevon_ted_command_cdeg']),
                    'right_elev': float(row['event/right_elevon_ted_command_cdeg']),
                    'low_rud':    float(row['event/lower_rudder_tel_command_cdeg']),
                    'up_rud':     float(row['event/upper_rudder_tel_command_cdeg']),
                    'l_tvc_up':   float(row['event/left_tvc_upper_command_cdeg']),
                    'l_tvc_lo':   float(row['event/left_tvc_lower_command_cdeg']),
                    'r_tvc_up':   float(row['event/right_tvc_upper_command_cdeg']),
                    'r_tvc_lo':   float(row['event/right_tvc_lower_command_cdeg']),
                    'l_eng':      float(row['event/left_engine_speed_command_prct_rpm']),
                    'r_eng':      float(row['event/right_engine_speed_command_prct_rpm']),
                }
            except (ValueError, KeyError) as e:
                self.cb.on_log(f"⚠ Frame {frame_idx} parse error: {e}")
                continue

            # Zero out channels we're not commanding
            if not use_actuation:
                cmds['left_elev'] = cmds['right_elev'] = 0.0
                cmds['low_rud'] = cmds['up_rud'] = 0.0
                cmds['l_tvc_up'] = cmds['l_tvc_lo'] = 0.0
                cmds['r_tvc_up'] = cmds['r_tvc_lo'] = 0.0
            if not use_propulsion:
                cmds['l_eng'] = cmds['r_eng'] = 0.0

            # Send command
            self._send_playback_frame(cmds)

            # Read feedback (non-blocking — use latest available)
            with self.master_lock:
                fb = self.master.recv_match(
                    type='PANDION_RR_ACTUATION_SYS_STATUS',
                    blocking=False,
                    timeout=0.005
                )
            if fb:
                # Compute deltas, update tracking, accumulate flags
                if use_actuation:
                    deltas = self._compute_frame_deltas(cmds, fb)
                    accumulated_flags |= self._update_tracking(
                        deltas, max_deltas, fb
                    )
                else:
                    accumulated_flags |= getattr(
                        fb, 'actuation_ibit_mon_status', 0
                    )

                # Emit to UI
                try:
                    self.cb.on_actuator_feedback(
                        _build_actuator_feedback_dict(fb)
                    )
                except AttributeError:
                    pass

            # Progress log every 10%
            pct = int((frame_idx / total_frames) * 100)
            if pct // 10 != last_pct_logged // 10:
                self.cb.on_log(
                    f"  [{pct:3d}%] Frame {frame_idx}/{total_frames} — "
                    f"mistracking_flags=0x{accumulated_flags:02X}"
                )
                self.cb.on_progress(pct)
                last_pct_logged = pct

            # Duration update
            if self.uut.test_start_time:
                self.cb.on_test_duration(
                    time.time() - self.uut.test_start_time
                )

            # Pace to 100 Hz
            elapsed = time.time() - frame_start
            remaining = interval - elapsed
            if remaining > 0:
                time.sleep(remaining)

        self.cb.on_log(
            f"\n✓ Profile streaming complete — "
            f"{len(profile)} frames, "
            f"mistracking_flags=0x{accumulated_flags:02X}"
        )

        # Exit PLAYBACK → back to OPERATE
        with self.master_lock:
            self.master.mav.pandion_rr_actuation_request_mode_send(
                requested_mode=ActuationMode.OPERATE
            )
        time.sleep(1.0)

        return accumulated_flags, max_deltas

    # ----------------------------------------------------------
    # Pass/fail evaluation
    # ----------------------------------------------------------

    def _evaluate_result(self, mistracking_flags, max_deltas):
        """
        Evaluate playback pass/fail.

        Pass criteria (mirrors Pandion IBIT):
          - No mistracking flags set in actuation_ibit_mon_status

        Returns:
            (success: bool, message: str)
        """
        self.cb.on_log("\n" + "=" * 60)
        self.cb.on_log("PLAYBACK RESULT EVALUATION")
        self.cb.on_log("=" * 60)

        # Log max deltas
        self.cb.on_log("Max command-feedback deltas:")
        for surface, delta in max_deltas.items():
            self.cb.on_log(f"  {surface:25s}: {delta:.1f} cdeg")

        # Evaluate mistracking flags
        if mistracking_flags == 0:
            self.cb.on_log("\n✓ PASS — No mistracking flags set")
            self.telemetry_logger.log_test_event(
                'PLAYBACK_PASS',
                f'All surfaces tracked correctly — max_deltas={max_deltas}'
            )
            return True, "Playback PASS — all surfaces tracked correctly"
        else:
            failed_surfaces = get_failed_surfaces(mistracking_flags)
            msg = f"Playback FAIL — mistracking on: {', '.join(failed_surfaces)}"
            self.cb.on_log(f"\n✗ FAIL — {msg}")
            self.cb.on_log(
                f"  Mistracking flags: 0x{mistracking_flags:02X}"
            )
            for surface in failed_surfaces:
                self.cb.on_log(f"  ✗ {surface}")
            self.telemetry_logger.log_test_event(
                'PLAYBACK_FAIL',
                f'{msg} — flags=0x{mistracking_flags:02X} '
                f'max_deltas={max_deltas}'
            )
            return False, msg

    # ----------------------------------------------------------
    # Power cycle helper
    # ----------------------------------------------------------

    def _power_cycle(self):
        """
        Power cycle the vehicle:
          1. Disable relay (power off)
          2. Wait 3 s
          3. Enable relay (power on)
          4. Wait for MAVLink heartbeat (up to 30 s)
        """
        self.cb.on_log("  Disabling relay (power off)...")
        self.daq.set_line(self.uut.relay_line, False)
        if self.telemetry_logger:
            self.telemetry_logger.log_relay_state(self.uut.relay_line, False)
        time.sleep(3.0)

        self.cb.on_log("  Enabling relay (power on)...")
        ok, msg = self.daq.set_line(self.uut.relay_line, True)
        if not ok:
            raise Exception(f"Relay re-enable failed: {msg}")
        if self.telemetry_logger:
            self.telemetry_logger.log_relay_state(self.uut.relay_line, True)
        time.sleep(self.stabilization_delay)

        self.cb.on_log("  Waiting for vehicle heartbeat after power cycle...")
        timeout = 30.0
        start = time.time()
        while time.time() - start < timeout:
            with self.master_lock:
                hb = self.master.wait_heartbeat(timeout=2.0)
            if hb:
                self.cb.on_log(
                    f"  ✓ Heartbeat received after "
                    f"{time.time() - start:.1f}s"
                )
                time.sleep(2.0)  # Allow boot to settle
                return
            time.sleep(0.5)

        raise Exception(
            f"Vehicle did not respond after power cycle within {timeout}s"
        )

    # ── Cleanup ──────────────────────────────────────────────────────────

    def _cleanup(self):
        """Restore vehicle state and close connections."""
        self.cb.on_log("→ Playback cleanup...")

        # Restore CLASSIC_MODE_EN = 0
        if self.preparation and self.master:
            try:
                self.cb.on_log(
                    "  → Restoring CLASSIC_MODE_EN = 0..."
                )
                self.preparation._set_param('CLASSIC_MODE_EN', 0)
                self.cb.on_log(
                    "  ✓ CLASSIC_MODE_EN restored — power cycle vehicle "
                    "before operational use"
                )
            except Exception as e:
                self.cb.on_log(
                    f"  ⚠ Could not restore CLASSIC_MODE_EN: {e}"
                )

            try:
                self.preparation.restore_original_state()
            except Exception as e:
                self.cb.on_log(f"  ⚠ State restore error: {e}")

        self._stop_heartbeat()
        self._close_resources()
        self.cb.on_log("✓ Playback cleanup complete")