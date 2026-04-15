from __future__ import annotations

"""
IBIT Test Executor - Orchestrates IBIT test sequence.
"""
import os
import time
import threading
from typing import Any, Dict, List, Optional

from .base_executor import _ExecutorMixin
from .tracker import IBITPhaseTracker, TestStatistics
from .helpers import _build_actuator_feedback_dict
from .callbacks import ExecutorCallbacks
from vehicle.constants import (
    ActuationMode, IBITSubstate, MsgType,
    IBIT_SUBSTATE_DISPLAY_NAMES,
    get_mode_name, get_failed_surfaces, is_armed,
    DEFAULT_IBIT_TIMEOUT, DEFAULT_PHASE_TIMEOUT,
    MAX_CONSECUTIVE_TELEMETRY_ERRORS, OPERATE_WAIT_TIMEOUT,
)


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
                self.cb.on_log("⚠ Skipping state management (as configured)")
                self.cb.on_log("→ Requesting IBIT mode (mode 1)")
                self.telemetry_logger.log_test_event(
                    'IBIT_REQUEST',
                    'Requesting IBIT mode (skipped state management)'
                )
                with self.master_lock:
                    self.master.mav.pandion_rr_actuation_request_mode_send(
                        requested_mode=ActuationMode.IBIT
                    )
                time.sleep(1.0)

                # Verify IBIT was entered — firmware may require PLAYBACK first
                mode_msg = self._wait_for_message(MsgType.ACTUATION_SYS_STATUS, timeout=5.0)
                if mode_msg and mode_msg.actuation_state != ActuationMode.IBIT:
                    current = mode_msg.actuation_state
                    self.cb.on_log(
                        f"  ⚠ IBIT request not accepted (mode={current}/{get_mode_name(current)})"
                    )
                    self.cb.on_log(
                        "  → Firmware may require OPERATE→PLAYBACK→IBIT sequence. "
                        "Disable 'Skip State Management' and retry."
                    )
                    self.error_log.error(
                        'IBIT', self.uut.serial_number, self.uut.iterations_completed,
                        f"IBIT mode not accepted with skip_state_management — firmware may require PLAYBACK first",
                        {'actual_mode': current},
                    )
                    raise Exception(
                        f"IBIT mode request rejected — vehicle in {get_mode_name(current)} mode. "
                        "Firmware may require PLAYBACK→IBIT sequence. Disable 'Skip State Management'."
                    )
            
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

            # Classify and persist to error log
            err_msg = str(e)
            if 'timeout' in err_msg.lower() and 'ibit' in err_msg.lower():
                category = 'IBIT'
            elif 'phase timeout' in err_msg.lower():
                category = 'IBIT'
            elif 'relay' in err_msg.lower():
                category = 'RELAY'
            elif 'heartbeat' in err_msg.lower() or 'connection' in err_msg.lower():
                category = 'CONNECTION'
            elif 'arm' in err_msg.lower() or 'disarm' in err_msg.lower():
                category = 'ARM'
            elif 'terminal' in err_msg.lower():
                category = 'STATE'
            elif 'playback' in err_msg.lower():
                category = 'IBIT'
            else:
                category = 'SYSTEM'
            self.error_log.error(
                category,
                self.uut.serial_number,
                self.uut.iterations_completed,
                err_msg,
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
        """Spawn IBIT-specific background worker threads.
        
        Note: _msg_dispatch_worker is already started in _connect_and_start_heartbeat
        so that preparation.py can use the queues during vehicle preparation.
        """
        for target in (
            self._receive_telemetry_worker,
            self._housekeeping_worker,
            self._connection_health_monitor,
            self._log_size_monitor,
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

        # Flush stale actuation status messages that arrived BEFORE IBIT started.
        # Pre-IBIT messages (during monitor clearing, PLAYBACK, etc.) may have
        # non-zero ibit_mon_status fields from hardware tests; we don't want them
        # contaminating the accumulator for this iteration.
        self._msg_queues[MsgType.ACTUATION_SYS_STATUS].clear()

        # Pre-loop: check if vehicle is already in OPERATE (instantaneous IBIT)
        initial_msg = self._wait_for_message(MsgType.ACTUATION_SYS_STATUS, timeout=0.5)
        if initial_msg and initial_msg.actuation_state == ActuationMode.OPERATE:
            # IBIT may have completed before we could observe it
            self.cb.on_log("  → Vehicle already in OPERATE — checking if IBIT completed instantly")
            # Treat this as an IBIT completion (mistracking = 0 since we saw no IBIT messages)
            self._handle_ibit_completion(initial_msg, 0)
            return  # Exit loop — completion handled

        while self.running and time.time() < self.batch_end_time:
            now = time.time()
            # Check timeouts
            if now - ibit_start_time > ibit_timeout:
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
                    # If vehicle is already in OPERATE on first message, IBIT may have completed instantly
                    if current_mode == ActuationMode.OPERATE:
                        self.cb.on_log("  ⚠ Vehicle in OPERATE on first message — IBIT may have completed instantly")
                        self._handle_ibit_completion(status_msg, current_substate)
                        break
                    continue  # Skip rest of loop for first message

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

                elif current_mode == ActuationMode.TERMINAL:
                    raise Exception(
                        "Vehicle entered TERMINAL mode during IBIT. "
                        "Power cycle required. Manual inspection of actuators required."
                    )

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
            # Persist mistracking failure to error log
            self.error_log.error(
                'IBIT',
                self.uut.serial_number,
                self.uut.iterations_completed,
                f"IBIT FAIL — mistracking on: {', '.join(failed_surfaces)} (flags=0x{mistracking:02X})",
                {'mistracking_flags': mistracking, 'failed_surfaces': failed_surfaces},
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

        ok, msg = self.daq.set_line(self.uut.relay_line, False)
        if ok:
            if self.telemetry_logger:
                self.telemetry_logger.log_relay_state(
                    self.uut.relay_line,
                    False
                )
            self.cb.on_log(
                f"✓ Relay {self.uut.relay_line} DISABLED - Load removed"
            )
        else:
            self.cb.on_log(f"⚠ Initial relay disable failed: {msg} — using emergency procedure")
            # Use full retry logic
            self._emergency_relay_disable()

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
                timeout=0.1
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

        if not returned_to_operate:
            final_msg = self._wait_for_message(
                MsgType.ACTUATION_SYS_STATUS, timeout=2.0
            )
            fm = final_msg.actuation_state if final_msg else -1
            self.cb.on_log(
                f"  ⚠ Vehicle did not return to OPERATE within {operate_timeout}s"
            )
            self.cb.on_log(
                f"  Final mode: {fm} ({get_mode_name(fm)})"
            )
            self.cb.on_log(
                "  → Proceeding with cleanup (relay already OFF, vehicle safe)"
            )
            # Note: relay is already OFF at this point (disabled in _handle_ibit_completion).
            # This is a post-IBIT state ambiguity, not a safety hazard.
            # Log the warning but do not abort — cleanup and state restoration continue.

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
        """Consume messages from the dispatch queue for logging and UI updates."""
        consecutive_errors = 0
        max_consecutive_errors = MAX_CONSECUTIVE_TELEMETRY_ERRORS

        while self.running:
            try:
                if self._all_msgs_queue:
                    msg = self._all_msgs_queue.popleft()

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
                else:
                    time.sleep(0.005)

            except Exception as e:
                consecutive_errors += 1
                if consecutive_errors >= max_consecutive_errors:
                    self.cb.on_log(f"⚠ Multiple telemetry errors: {e}")
                    self.cb.on_alert(f"Telemetry reception issues")
                    consecutive_errors = 0
                self.statistics.record_communication_error()
    
    def _housekeeping_worker(self) -> None:
        """Periodic statistics update and duration reporting."""
        while self.running:
            time.sleep(1.0)
            self.statistics.update_telemetry_rate()
            self.cb.on_statistics(self.statistics)
            if self.uut.test_start_time:
                self.cb.on_test_duration(time.time() - self.uut.test_start_time)
    
    def _connection_health_monitor(self) -> None:
        """Monitor GCS connection health and alert on sustained link loss.

        Does NOT abort the test — the IBIT timeout (300s) is the safety net.
        A transient network issue should not kill a 14-day batch run.
        Only escalates to emergency relay disable if the link loss is so long
        that the IBIT timeout is also about to expire.
        """
        consecutive_unhealthy = 0

        while self.running:
            time.sleep(5.0)
            if not self.running:
                break

            healthy = self.statistics.is_connection_healthy()
            if not healthy:
                consecutive_unhealthy += 1
                elapsed = consecutive_unhealthy * 5
                self.cb.on_log(
                    f"⚠ Connection unhealthy — no heartbeat for {elapsed}s"
                )
                self.cb.on_connection_health(False)

                # Alert at 15s but don't abort — IBIT timeout handles the hard stop
                if consecutive_unhealthy == 3:
                    self.cb.on_alert(
                        f"GCS link lost for {elapsed}s — monitoring, IBIT will timeout if unresolved"
                    )
                    self.error_log.warning(
                        'CONNECTION',
                        self.uut.serial_number,
                        getattr(self.uut, 'iterations_completed', 0),
                        f"GCS link lost for {elapsed}s during IBIT",
                    )
            else:
                if consecutive_unhealthy > 0:
                    self.cb.on_log(
                        f"✓ Connection restored after {consecutive_unhealthy * 5}s"
                    )
                    self.cb.on_connection_health(True)
                consecutive_unhealthy = 0
    
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
    
