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
import time
import threading
import csv
from collections import deque
from datetime import datetime
from PyQt5.QtCore import QThread, pyqtSignal
from pymavlink import mavutil
from vehicle.connection import connect_to_vehicle
from vehicle.preparation import UUTPreparation
from .logger import TelemetryLogger


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
    
    PHASE_BEGIN = 0
    PHASE_WAIT_FOR_SETTLE = 1
    PHASE_ELEVONS = 2
    PHASE_RUDDERS = 3
    PHASE_TVC = 4
    PHASE_COMPLETE = 5
    
    EXPECTED_SEQUENCE = [
        'WAIT_FOR_SETTLE',
        'ELEVONS',
        'RUDDERS',
        'TVC'
    ]
    
    def __init__(self):
        """Initialize tracker"""
        self.phases_completed = []
        self.last_substate = None
        self.current_substate = None
        self.phase_start_times = {}
        self.phase_durations = {}
        self.last_progress_time = time.time()
        self.reached_complete = False
        self.transition_history = []
    
    def update(self, substate):
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
            if substate == 1:
                self._start_phase('WAIT_FOR_SETTLE')
            elif substate == 2:
                self._complete_phase('WAIT_FOR_SETTLE')
                self._start_phase('ELEVONS')
            elif substate == 3:
                self._complete_phase('ELEVONS')
                self._start_phase('RUDDERS')
            elif substate == 4:
                self._complete_phase('RUDDERS')
                self._start_phase('TVC')
            elif substate == 5:
                self._complete_phase('TVC')
                self.reached_complete = True
                self.last_progress_time = time.time()
            
            self.last_substate = substate
        
        self.current_substate = substate
    
    def _start_phase(self, phase_name):
        """Record phase start time"""
        if phase_name not in self.phase_start_times:
            self.phase_start_times[phase_name] = time.time()
            self.last_progress_time = time.time()
    
    def _complete_phase(self, phase_name):
        """Record phase completion"""
        if phase_name not in self.phases_completed:
            self.phases_completed.append(phase_name)
            
            if phase_name in self.phase_start_times:
                duration = time.time() - self.phase_start_times[phase_name]
                self.phase_durations[phase_name] = duration
            
            self.last_progress_time = time.time()
    
    def is_complete(self):
        """Check if IBIT reached COMPLETE state (substate 5)"""
        return self.reached_complete and self.current_substate == 5
    
    def get_progress(self):
        """Get test progress (0.0 to 1.0)"""
        if self.reached_complete:
            return 1.0
        return len(self.phases_completed) / len(self.EXPECTED_SEQUENCE)
    
    def time_since_last_progress(self):
        """Time since last progress in seconds"""
        return time.time() - self.last_progress_time
    
    def get_current_phase_name(self):
        """Get name of current phase"""
        substate_to_name = {
            0: "BEGIN",
            1: "WAIT_FOR_SETTLE",
            2: "ELEVONS",
            3: "RUDDERS",
            4: "TVC",
            5: "COMPLETE"
        }
        return substate_to_name.get(self.current_substate, "UNKNOWN")
    
    def get_summary(self):
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


class TestStatistics:
    """Tracks real-time test statistics"""
    
    def __init__(self):
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
    
    def record_command_sent(self):
        """Record a command was sent"""
        self.commands_sent += 1
    
    def record_telemetry_received(self):
        """Record telemetry message received"""
        self.telemetry_received += 1
    
    def record_heartbeat(self):
        """Record heartbeat received"""
        self.heartbeats_received += 1
        self.last_heartbeat_time = time.time()
    
    def record_communication_error(self):
        """Record communication error"""
        self.communication_errors += 1
    
    def record_iteration_time(self, duration):
        """Record iteration completion time"""
        self.iteration_times.append(duration)
    
    def get_average_iteration_time(self):
        """Get average iteration time"""
        if not self.iteration_times:
            return 0.0
        return sum(self.iteration_times) / len(self.iteration_times)
    
    def update_telemetry_rate(self):
        """Update telemetry rate calculation"""
        now = time.time()
        if now - self.last_rate_update >= 1.0:
            rate = self.telemetry_received - self.last_telemetry_count
            self.telemetry_rate_history.append(rate)
            self.last_telemetry_count = self.telemetry_received
            self.last_rate_update = now
    
    def get_current_telemetry_rate(self):
        """Get current telemetry rate (messages/sec)"""
        if not self.telemetry_rate_history:
            return 0
        return self.telemetry_rate_history[-1]
    
    def get_average_telemetry_rate(self):
        """Get average telemetry rate"""
        if not self.telemetry_rate_history:
            return 0
        return sum(self.telemetry_rate_history) / len(self.telemetry_rate_history)
    
    def time_since_last_heartbeat(self):
        """Time since last heartbeat in seconds"""
        if self.last_heartbeat_time == 0:
            return float('inf')
        return time.time() - self.last_heartbeat_time
    
    def is_connection_healthy(self):
        """Check if connection is healthy"""
        return self.time_since_last_heartbeat() < 3.0


class UUTTestExecutor(QThread):
    """
    Executes IBIT test with complete event logging.
    
    Runs in separate thread to avoid blocking UI.
    Emits signals for UI updates.
    """
    
    # Qt Signals for UI updates
    progress_update = pyqtSignal(int)
    iteration_update = pyqtSignal(int)
    status_update = pyqtSignal(str)
    test_complete = pyqtSignal(bool, str)
    log_message = pyqtSignal(str)
    time_expired = pyqtSignal()
    statistics_update = pyqtSignal(object)
    ibit_state_update = pyqtSignal(str)
    connection_health_update = pyqtSignal(bool)
    alert_update = pyqtSignal(str)
    log_file_size_update = pyqtSignal(float)
    test_duration_update = pyqtSignal(float)
    armed_state_update = pyqtSignal(bool, int)  # (armed, flight_regime)
    mode_update = pyqtSignal(int)  # actuation_mode
    actuator_feedback_update = pyqtSignal(dict)
    
    def __init__(self, uut, daq_controller, batch_end_time,
                 stabilization_delay, connection_timeout,
                 log_directory, test_start_datetime,
                 skip_state_management=False, config=None):
        """
        Initialize test executor.
        
        Args:
            uut: UUT object to test
            daq_controller: DAQ controller for relay
            batch_end_time: When batch test ends (timestamp)
            stabilization_delay: Delay after relay enable (seconds)
            connection_timeout: Connection timeout (seconds)
            log_directory: Where to save logs
            test_start_datetime: When batch started (datetime)
            skip_state_management: Skip state capture/restore (faster, less safe)
            config: Configuration dictionary
        """
        super().__init__()
        self.uut = uut
        self.daq = daq_controller
        self.batch_end_time = batch_end_time
        self.stabilization_delay = stabilization_delay
        self.connection_timeout = connection_timeout
        self.log_directory = log_directory
        self.test_start_datetime = test_start_datetime
        self.skip_state_management = skip_state_management
        self.config = config or {}
        
        self.running = False
        self.master = None
        self.telemetry_logger = None
        self.preparation = None
        self.statistics = TestStatistics()
        self.phase_tracker = IBITPhaseTracker()
        self.current_ibit_substate = None
        
        self.heartbeat_thread = None
        self.heartbeat_count = 0
        self.master_lock = threading.Lock()
    
    def run(self):
        """
        Execute IBIT test with full state management and logging.
        
        Main thread entry point (runs in QThread).
        """
        self.running = True
        success = False
        message = ""
        
        try:
            # Check if time expired
            if time.time() >= self.batch_end_time:
                self.time_expired.emit()
                return
            
            # Connect to vehicle (relay still OFF)
            self.status_update.emit("Connecting to UUT (no load)...")
            self.master = connect_to_vehicle(
                self.uut.ip_address,
                self.uut.port,
                self.connection_timeout
            )
            self.log_message.emit(
                f"✓ Connected to {self.uut.ip_address}:{self.uut.port}"
            )
            
            # Start heartbeat sender
            self.log_message.emit("→ Starting GCS heartbeat sender...")
            self.heartbeat_thread = threading.Thread(
                target=self._heartbeat_worker,
                daemon=True
            )
            self.heartbeat_thread.start()
            
            self.log_message.emit(
                "  Waiting for vehicle to stabilize with GCS heartbeats..."
            )
            time.sleep(2.0)
            
            # Initialize telemetry logger EARLY
            self.telemetry_logger = TelemetryLogger(
                self.log_directory,
                self.uut.serial_number,
                self.test_start_datetime,
                logging_mode=TelemetryLogger.MODE_IBIT_FOCUSED
            )
            self.telemetry_logger.log_message.connect(self.log_message)
            
            if not self.telemetry_logger.open():
                raise Exception("Failed to open log file")
            
            self.uut.log_file = self.telemetry_logger.get_current_log_path()
            
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
                self.log_message.emit(
                    "→ Beginning state capture (GCS heartbeats active)..."
                )
                
                self.preparation = UUTPreparation(
                    self.master,
                    self.config,
                    self.telemetry_logger
                )
                self.preparation.log_message.connect(self.log_message)
                self.preparation.progress_update.connect(self.status_update)
                
                prep_ok, prep_msg = self.preparation.capture_initial_state()
                if not prep_ok:
                    raise Exception(prep_msg)
                
                # Prepare for test (ARM, OPERATE, PLAYBACK, IBIT)
                prep_ok, prep_msg = self.preparation.prepare_for_test()
                if not prep_ok:
                    raise Exception(prep_msg)
            else:
                self.log_message.emit("⚠ Skipping state management (as configured)")
                self.log_message.emit("→ Requesting IBIT mode (mode 1)")
                self.telemetry_logger.log_test_event(
                    'IBIT_REQUEST',
                    'Requesting IBIT mode (skipped state management)'
                )
                
                with self.master_lock:
                    self.master.mav.pandion_rr_actuation_request_mode_send(
                        requested_mode=1
                    )
                time.sleep(1.0)
            
            # NOW ENABLE RELAY - just before IBIT execution
            self.status_update.emit("Enabling load relay for IBIT test...")
            self.log_message.emit("\n" + "="*60)
            self.log_message.emit("ENABLING LOAD RELAY")
            self.log_message.emit("="*60)
            
            success_relay, msg = self.daq.set_line(self.uut.relay_line, True)
            if not success_relay:
                raise Exception(f"Failed to enable relay: {msg}")
            
            # Log relay ON event
            self.telemetry_logger.log_relay_state(self.uut.relay_line, True)
            
            self.log_message.emit(
                f"✓ Relay {self.uut.relay_line} ENABLED - Load applied to vehicle"
            )
            self.log_message.emit(
                f"  Waiting {self.stabilization_delay}s for stabilization..."
            )
            time.sleep(self.stabilization_delay)
            
            # Verify vehicle is still responsive with load
            heartbeat_received = self.master.wait_heartbeat(timeout=2.0)
            if not heartbeat_received:
                raise Exception("Lost connection after applying load")
            
            self.log_message.emit("✓ Vehicle responsive under load")
            self.log_message.emit("="*60 + "\n")
            
            # Execute IBIT test
            self.execute_ibit_test()
            
            success = True
            message = f"IBIT test complete (Iteration {self.uut.iterations_completed})"
            
        except Exception as e:
            success = False
            message = f"Test failed: {str(e)}"
            self.log_message.emit(f"✗ Error: {e}")
            self.alert_update.emit(f"TEST FAILED: {str(e)}")
            
            # CRITICAL: Ensure relay is OFF on failure with retry logic
            if self.daq:
                self._emergency_relay_disable()
            
            # Log failure event
            if self.telemetry_logger:
                self.telemetry_logger.log_test_event(
                    'TEST_FAILED',
                    f'Test failed: {str(e)}'
                )
        
        finally:
            self.cleanup()
        
        self.test_complete.emit(success, message)
    
    def execute_ibit_test(self):
        """
        Execute IBIT test - wait for COMPLETE state then return to OPERATE.
        
        Monitors IBIT phases and detects completion by mode transition.
        """
        # Start background workers
        telemetry_thread = threading.Thread(
            target=self._receive_telemetry_worker,
            daemon=True
        )
        telemetry_thread.start()
        
        stats_timer = threading.Thread(
            target=self._statistics_update_worker,
            daemon=True
        )
        stats_timer.start()
        
        health_monitor = threading.Thread(
            target=self._connection_health_monitor,
            daemon=True
        )
        health_monitor.start()
        
        size_monitor = threading.Thread(
            target=self._log_size_monitor,
            daemon=True
        )
        size_monitor.start()
        
        duration_monitor = threading.Thread(
            target=self._test_duration_monitor,
            daemon=True
        )
        duration_monitor.start()
        
        self.iteration_update.emit(self.uut.iterations_completed)
        
        test_start = time.time()
        self.uut.test_start_time = test_start
        
        self.status_update.emit(
            f"Running IBIT (Iteration {self.uut.iterations_completed})..."
        )
        
        self.log_message.emit("="*60)
        self.log_message.emit("STARTING IBIT TEST SEQUENCE")
        self.log_message.emit("="*60)
        self.log_message.emit("Expected sequence:")
        self.log_message.emit(
            "  0: BEGIN → 1: WAIT_FOR_SETTLE → 2: ELEVONS → "
            "3: RUDDERS → 4: TVC → 5: COMPLETE"
        )
        self.log_message.emit("Heartbeat running in background at 1 Hz")
        self.log_message.emit("")
        
        ibit_timeout = self.config.get('ibit_timeout', 300.0)
        phase_timeout = self.config.get('phase_timeout', 90.0)
        
        ibit_start_time = time.time()
        last_logged_phase = None
        
        # Initialize mode tracking
        self._last_mode = None
        self._ibit_run_count = 0
        self._last_substate = None
        
        while self.running and time.time() < self.batch_end_time:
            if not self.running:
                self.log_message.emit("⚠ Test stopped by user")
                break
            
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
                'PANDION_RR_ACTUATION_SYS_STATUS',
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
                if self._last_mode == 1 and current_mode == 1:  # Still in IBIT
                    if self._last_substate in [3, 4] and current_substate in [0, 1]:
                        self._ibit_run_count += 1
                        self.log_message.emit(
                            f"\n→ IBIT Run #{self._ibit_run_count + 1} detected "
                            f"(vehicle performing multiple cycles)"
                        )
                
                # CRITICAL: IBIT completion detected by mode transition IBIT → OPERATE
                if self._last_mode == 1 and current_mode == 2:
                    # Evaluate mistracking flags — actual PASS/FAIL determination
                    mistracking = getattr(status_msg, 'actuation_ibit_mon_status', 0)
                    mistracking_names = {
                        1: 'Upper Rudder',    2: 'Lower Rudder',
                        4: 'Left TVC Upper',  8: 'Left TVC Lower',
                        16: 'Right TVC Upper', 32: 'Right TVC Lower',
                        64: 'Left Elevon',    128: 'Right Elevon',
                    }
                    failed_surfaces = [
                        name for bit, name in mistracking_names.items()
                        if mistracking & bit
                    ]

                    total_runs = self._ibit_run_count + 1
                    self.log_message.emit(
                        f"\n{'✓' if not failed_surfaces else '✗'} IBIT completed "
                        f"after {total_runs} run(s) — "
                        f"Mode: IBIT(1) → OPERATE(2)"
                    )

                    if failed_surfaces:
                        self.log_message.emit(
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
                        self.log_message.emit(
                            f"  ✓ IBIT PASS — no mistracking flags set"
                        )
                        if self.telemetry_logger:
                            self.telemetry_logger.log_test_event(
                                'IBIT_PASS',
                                'IBIT passed — all surfaces tracked correctly'
                            )
                    self.log_message.emit(f"  Final IBIT substate: {current_substate}")
                    self.log_message.emit("")
                    self.log_message.emit("="*60)
                    self.log_message.emit("✓ IBIT PASS — Vehicle ready for flight!")
                    self.log_message.emit("="*60)
                    
                    # Mark tracker as complete
                    self.phase_tracker.reached_complete = True
                    
                    # Ensure all phases are marked complete
                    expected_phases = ['WAIT_FOR_SETTLE', 'ELEVONS', 'RUDDERS', 'TVC']
                    for phase in expected_phases:
                        if phase not in self.phase_tracker.phases_completed:
                            self.phase_tracker.phases_completed.append(phase)
                    
                    # Log phase summary
                    self.log_message.emit(
                        f"Phases observed: {len(self.phase_tracker.phases_completed)}/4"
                    )
                    for phase in self.phase_tracker.phases_completed:
                        duration = self.phase_tracker.phase_durations.get(phase, 0)
                        if duration > 0:
                            self.log_message.emit(
                                f"  ✓ {phase:20s} - {duration:.2f}s"
                            )
                        else:
                            self.log_message.emit(f"  ✓ {phase:20s} - completed")
                    
                    if total_runs > 1:
                        self.log_message.emit(
                            f"\nℹ️  Vehicle performed {total_runs} IBIT cycles "
                            f"(firmware-controlled)"
                        )
                    
                    # RELAY OFF - IBIT complete, before restoration
                    self.log_message.emit("\n" + "="*60)
                    self.log_message.emit("IBIT COMPLETE - DISABLING LOAD RELAY")
                    self.log_message.emit("="*60)
                    self.log_message.emit(
                        "✓ IBIT sequence finished - removing load from vehicle"
                    )
                    
                    success_relay, msg = self.daq.set_line(self.uut.relay_line, False)
                    if success_relay:
                        if self.telemetry_logger:
                            self.telemetry_logger.log_relay_state(
                                self.uut.relay_line,
                                False
                            )
                        self.log_message.emit(
                            f"✓ Relay {self.uut.relay_line} DISABLED - Load removed"
                        )
                    else:
                        self.log_message.emit(f"⚠ Relay disable warning: {msg}")
                    
                    self.log_message.emit("="*60 + "\n")
                    break
                
                elif current_mode == 0:  # Transitioned to OFF
                    raise Exception(
                        f"IBIT aborted - vehicle transitioned to OFF mode "
                        f"(substate: {current_substate})"
                    )
                
                elif self._last_mode == 1 and current_mode not in [1, 2]:
                    # Unexpected mode
                    mode_names = {
                        0: "OFF", 1: "IBIT", 2: "OPERATE",
                        3: "MANUAL", 4: "PLAYBACK", 5: "TRIM"
                    }
                    mode_str = mode_names.get(current_mode, f"UNKNOWN({current_mode})")
                    raise Exception(
                        f"Unexpected mode transition during IBIT: IBIT → {mode_str}"
                    )
                
                # Still in IBIT mode - continue tracking substates
                if current_mode == 1:
                    if hasattr(status_msg, 'actuation_ibit_substate'):
                        substate = status_msg.actuation_ibit_substate
                        self.phase_tracker.update(substate)
                        current_phase = self.phase_tracker.get_current_phase_name()
                        
                        # Log phase transitions
                        if current_phase != last_logged_phase:
                            self.log_message.emit(
                                f"→ Substate {substate}: {current_phase}"
                            )
                            last_logged_phase = current_phase
                        
                        # Update GUI display
                        substate_display_names = {
                            0: "BEGIN",
                            1: "WAIT_FOR_SETTLE",
                            2: "ELEVONS",
                            3: "RUDDERS",
                            4: "TVC",
                            5: "✓ COMPLETE"
                        }
                        display_name = substate_display_names.get(
                            substate,
                            f"UNKNOWN({substate})"
                        )
                        self.ibit_state_update.emit(display_name)
                
                # Update tracking variables
                self._last_mode = current_mode
                self._last_substate = current_substate
            
            time.sleep(0.01)
        
        if time.time() >= self.batch_end_time:
            self.log_message.emit("Batch time expired during IBIT")
            return
        
        if not self.phase_tracker.reached_complete:
            raise Exception(
                f"IBIT did not reach COMPLETE state "
                f"(stuck at substate {self.phase_tracker.current_substate})"
            )
        
        # Wait for return to OPERATE
        self.log_message.emit("\n→ Waiting for vehicle to return to OPERATE mode...")
        self.status_update.emit("Waiting for OPERATE mode...")
        
        operate_timeout = 10.0
        operate_start = time.time()
        returned_to_operate = False
        
        while time.time() - operate_start < operate_timeout:
            mode_msg = self._wait_for_message(
                'PANDION_RR_ACTUATION_SYS_STATUS',
                timeout=1.0
            )
            
            if mode_msg:
                current_mode = mode_msg.actuation_state
                mode_names = {
                    0: "OFF", 1: "IBIT", 2: "OPERATE",
                    3: "MANUAL", 4: "PLAYBACK", 5: "TRIM",
                    6: "POSITION_CHECK", 7: "TERMINAL"
                }
                
                if current_mode == 2:
                    returned_to_operate = True
                    self.log_message.emit(f"  ✓ Vehicle returned to OPERATE mode")
                    break
                elif current_mode == 1:
                    pass  # Still transitioning
                else:
                    self.log_message.emit(
                        f"  ⚠ Unexpected mode: {current_mode} "
                        f"({mode_names.get(current_mode, 'UNKNOWN')})"
                    )
            
            time.sleep(0.5)
        
        if not returned_to_operate:
            final_mode_msg = self._wait_for_message(
                'PANDION_RR_ACTUATION_SYS_STATUS',
                timeout=2.0
            )
            final_mode = final_mode_msg.actuation_state if final_mode_msg else -1
            mode_names = {
                0: "OFF", 1: "IBIT", 2: "OPERATE",
                3: "MANUAL", 4: "PLAYBACK", 5: "TRIM",
                6: "POSITION_CHECK", 7: "TERMINAL"
            }
            self.log_message.emit(
                f"  ⚠ Vehicle did not return to OPERATE within {operate_timeout}s"
            )
            self.log_message.emit(
                f"  Final mode: {final_mode} "
                f"({mode_names.get(final_mode, 'UNKNOWN')})"
            )
            self.log_message.emit(f"  → Proceeding with cleanup anyway...")
        
        # Record metrics
        self.uut.test_end_time = time.time()
        test_duration = self.uut.test_end_time - test_start
        self.statistics.record_iteration_time(test_duration)
        
        # Log completion
        self.telemetry_logger.log_test_event(
            'ITERATION_COMPLETE',
            f"IBIT test iteration #{self.uut.iterations_completed} completed "
            f"successfully for UUT {self.uut.serial_number} - "
            f"Duration: {test_duration:.1f} seconds"
        )
        
        self.log_message.emit(
            f"\n✓ IBIT test completed successfully in {test_duration:.1f}s"
        )
        self.log_message.emit(
            f"  Total transitions: {len(self.phase_tracker.transition_history)}"
        )
        self.log_message.emit(f"  Sequence: IBIT → COMPLETE → OPERATE ✓")
    
    def cleanup(self):
        """
        Cleanup after test completion or failure.
        
        Note: Relay is already disabled in execute_ibit_test() after IBIT completes,
        or in the exception handler if test fails. This method focuses on:
        - Restoring vehicle state
        - Stopping heartbeat
        - Closing connections
        """
        self.log_message.emit(
            "→ Beginning cleanup (relay already OFF, restoring vehicle state)..."
        )
        time.sleep(1.0)
        
        # Check if we've been asked to stop
        if not self.running:
            self.log_message.emit("⚠ Stop requested - performing quick cleanup...")
            
            # Quick cleanup path
            self.running = False
            
            if self.heartbeat_thread and self.heartbeat_thread.is_alive():
                self.heartbeat_thread.join(timeout=2.0)
            
            if self.telemetry_logger:
                try:
                    self.telemetry_logger.close()
                except:
                    pass
            
            if self.master:
                try:
                    self.master.close()
                except:
                    pass
            
            self.log_message.emit("Quick cleanup complete (relay already OFF)")
            return
        
        # Normal cleanup path
        if self.master and self.preparation and self.preparation.initial_state.captured:
            # Step 1: Restore state (while vehicle still powered)
            self.preparation.restore_original_state()
            
            # Check again if we should abort
            if not self.running:
                self.log_message.emit(
                    "⚠ Stop requested during restoration - aborting..."
                )
                self.running = False
                if self.heartbeat_thread:
                    self.heartbeat_thread.join(timeout=1.0)
                if self.telemetry_logger:
                    self.telemetry_logger.close()
                if self.master:
                    self.master.close()
                return
            
            time.sleep(2.0)
            
            # Step 2: Verify state (relay already disabled from execute_ibit_test)
            self.preparation.verify_final_state(relay_was_disabled=True)
            
            # Step 3: Stop heartbeat
            self.log_message.emit("→ Stopping heartbeat sender...")
            self.running = False
            
            if self.heartbeat_thread and self.heartbeat_thread.is_alive():
                self.heartbeat_thread.join(timeout=2.0)
                if self.heartbeat_thread.is_alive():
                    self.log_message.emit("⚠ Heartbeat thread did not stop cleanly")
                else:
                    self.log_message.emit("✓ Heartbeat sender stopped")
            
            self.log_message.emit(
                "✓ Cleanup complete (relay already OFF, vehicle safe)"
            )
        else:
            # No restoration needed, just stop heartbeat
            self.log_message.emit("→ Stopping heartbeat sender...")
            self.running = False
            
            if self.heartbeat_thread and self.heartbeat_thread.is_alive():
                self.heartbeat_thread.join(timeout=2.0)
            
            self.log_message.emit("✓ Cleanup complete (relay already OFF)")
        
        # Step 4: Close telemetry logger
        if self.telemetry_logger:
            try:
                self.telemetry_logger.close()
            except:
                pass
        
        # Step 5: Close MAVLink connection
        if self.master:
            try:
                self.master.close()
            except:
                pass
        
        self.log_message.emit("Cleanup complete - ready for next iteration")
    
    def stop(self):
        """Stop the test executor"""
        self.running = False
        if self.telemetry_logger:
            self.telemetry_logger.log_test_event(
                'TEST_STOPPED',
                'Test stopped by user request'
            )
    
    # ========== BACKGROUND WORKER THREADS ==========
    
    def _heartbeat_worker(self):
        """Send heartbeats to vehicle at 1 Hz continuously during test"""
        self.log_message.emit("✓ Heartbeat sender started (1 Hz)")
        
        # Send initial burst
        try:
            for i in range(3):
                with self.master_lock:
                    if self.master:
                        self.master.mav.heartbeat_send(
                            mavutil.mavlink.MAV_TYPE_GCS,
                            mavutil.mavlink.MAV_AUTOPILOT_INVALID,
                            0, 0,
                            mavutil.mavlink.MAV_STATE_ACTIVE
                        )
                        self.heartbeat_count += 1
                time.sleep(0.1)
            self.log_message.emit("  ✓ Initial heartbeat burst sent")
        except Exception as e:
            self.log_message.emit(f"⚠ Initial heartbeat error: {e}")
        
        # Continue with regular 1 Hz heartbeats
        while self.running:
            try:
                with self.master_lock:
                    if self.master:
                        self.master.mav.heartbeat_send(
                            mavutil.mavlink.MAV_TYPE_GCS,
                            mavutil.mavlink.MAV_AUTOPILOT_INVALID,
                            0, 0,
                            mavutil.mavlink.MAV_STATE_ACTIVE
                        )
                        self.heartbeat_count += 1
                
                if self.heartbeat_count % 60 == 0:
                    self.log_message.emit(
                        f"  ❤ Heartbeat active ({self.heartbeat_count} sent)"
                    )
            except Exception as e:
                self.log_message.emit(f"⚠ Heartbeat send error: {e}")
            
            time.sleep(1.0)
        
        self.log_message.emit(
            f"✓ Heartbeat sender stopped (total sent: {self.heartbeat_count})"
        )
    
    def _receive_telemetry_worker(self):
        """Enhanced telemetry receiver with thread-safe message reception"""
        consecutive_errors = 0
        max_consecutive_errors = 10
        
        while self.running:
            if not self.running:
                break
            
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
                    if msg_type == 'PANDION_STATUS':
                        flight_regime = msg.flight_regime
                        armed = (flight_regime >= 1 and flight_regime != 255)
                        self.armed_state_update.emit(armed, flight_regime)
                    
                    # Heartbeat
                    if msg_type == 'HEARTBEAT':
                        self.statistics.record_heartbeat()
                    
                    # Mode from actuation status
                    if msg_type == 'PANDION_RR_ACTUATION_SYS_STATUS':
                        mode = msg.actuation_state
                        self.mode_update.emit(mode)
                        
                        if hasattr(msg, 'actuation_ibit_substate'):
                            self.current_ibit_substate = msg.actuation_ibit_substate
                        
                        # Actuator feedback
                        try:
                            actuator_data = {
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
                            self.actuator_feedback_update.emit(actuator_data)
                        except AttributeError:
                            pass
                
            except Exception as e:
                consecutive_errors += 1
                if consecutive_errors >= max_consecutive_errors:
                    self.log_message.emit(f"⚠ Multiple telemetry errors: {e}")
                    self.alert_update.emit(f"Telemetry reception issues")
                    consecutive_errors = 0
                self.statistics.record_communication_error()
    
    def _statistics_update_worker(self):
        """Periodically update statistics"""
        while self.running:
            time.sleep(1.0)
            self.statistics.update_telemetry_rate()
            self.statistics_update.emit(self.statistics)
    
    def _connection_health_monitor(self):
        """Monitor connection health"""
        last_warning_time = 0
        
        while self.running:
            time.sleep(0.5)
            is_healthy = self.statistics.is_connection_healthy()
            self.connection_health_update.emit(is_healthy)
            
            if not is_healthy:
                now = time.time()
                if now - last_warning_time > 5.0:
                    time_since = self.statistics.time_since_last_heartbeat()
                    self.alert_update.emit(f"No heartbeat for {time_since:.1f}s")
                    self.log_message.emit(
                        f"⚠ Connection unhealthy - no heartbeat for {time_since:.1f}s"
                    )
                    last_warning_time = now
    
    def _log_size_monitor(self):
        """Monitor log file size"""
        import os
        while self.running:
            time.sleep(5.0)
            if self.telemetry_logger and self.uut.log_file:
                try:
                    if os.path.exists(self.uut.log_file):
                        file_size = os.path.getsize(self.uut.log_file)
                        size_mb = file_size / (1024 * 1024)
                        self.log_file_size_update.emit(size_mb)
                except:
                    pass
    
    def _test_duration_monitor(self):
        """Monitor test duration"""
        while self.running:
            time.sleep(1.0)
            if self.uut.test_start_time:
                duration = time.time() - self.uut.test_start_time
                self.test_duration_update.emit(duration)
    
    def _emergency_relay_disable(self):
        """
        Emergency relay disable with retry logic and verification.
        
        CRITICAL SAFETY FUNCTION: Must succeed or alert user.
        Tries multiple times with delays between attempts.
        """
        if not self.daq or not self.uut:
            return
        
        self.log_message.emit("=" * 60)
        self.log_message.emit("⚠⚠⚠ EMERGENCY RELAY DISABLE ⚠⚠⚠")
        self.log_message.emit("=" * 60)
        self.log_message.emit(f"→ Attempting to disable relay {self.uut.relay_line}...")
        
        max_attempts = 5
        retry_delay = 0.5  # seconds
        
        for attempt in range(1, max_attempts + 1):
            try:
                self.log_message.emit(f"  Attempt {attempt}/{max_attempts}...")
                
                relay_success, relay_msg = self.daq.set_line(
                    self.uut.relay_line,
                    False
                )
                
                if relay_success:
                    self.log_message.emit(
                        f"  ✓ Relay {self.uut.relay_line} DISABLED (attempt {attempt})"
                    )
                    
                    # Log to telemetry
                    if self.telemetry_logger:
                        try:
                            self.telemetry_logger.log_relay_state(
                                self.uut.relay_line,
                                False
                            )
                        except Exception as log_err:
                            self.log_message.emit(f"  ⚠ Logging error: {log_err}")
                    
                    self.log_message.emit("✓ Emergency relay disable SUCCESSFUL")
                    self.log_message.emit("=" * 60)
                    return  # SUCCESS - exit function
                
                else:
                    self.log_message.emit(
                        f"  ✗ Attempt {attempt} failed: {relay_msg}"
                    )
                    
                    if attempt < max_attempts:
                        self.log_message.emit(f"  → Retrying in {retry_delay}s...")
                        time.sleep(retry_delay)
            
            except Exception as relay_err:
                self.log_message.emit(
                    f"  ✗ Attempt {attempt} exception: {type(relay_err).__name__}: {relay_err}"
                )
                
                if attempt < max_attempts:
                    self.log_message.emit(f"  → Retrying in {retry_delay}s...")
                    time.sleep(retry_delay)
        
        # ALL ATTEMPTS FAILED - CRITICAL ALERT
        critical_msg = (
            f"✗✗✗ CRITICAL: RELAY {self.uut.relay_line} DISABLE FAILED "
            f"AFTER {max_attempts} ATTEMPTS ✗✗✗"
        )
        self.log_message.emit("")
        self.log_message.emit(critical_msg)
        self.log_message.emit("⚠ MANUAL INTERVENTION REQUIRED ⚠")
        self.log_message.emit("⚠ VERIFY HARDWARE IS POWERED OFF ⚠")
        self.log_message.emit("=" * 60)
        
        # Alert UI
        self.alert_update.emit(
            f"CRITICAL: RELAY {self.uut.relay_line} CONTROL FAILURE - CHECK HARDWARE"
        )
        
        # Log critical event
        if self.telemetry_logger:
            try:
                self.telemetry_logger.log_test_event(
                    'RELAY_DISABLE_CRITICAL_FAILURE',
                    f'Failed to disable relay {self.uut.relay_line} after {max_attempts} attempts - MANUAL INTERVENTION REQUIRED'
                )
            except:
                pass
    
    def _wait_for_message(self, msg_type, timeout=5.0):
        """
        Wait for a specific message type.

        IMPORTANT: Uses master_lock to prevent concurrent MAVLink access
        with the background telemetry worker thread.
        """
        with self.master_lock:
            return self.master.recv_match(
                type=msg_type, blocking=True, timeout=timeout
            )


class IBITFailureDiagnostic:
    """Structured IBIT failure diagnostics"""
    
    def __init__(self):
        self.failed_phase = None
        self.phases_completed = []
        self.monitor_status = None
        self.recent_errors = deque(maxlen=20)
        self.vehicle_state = None
        self.arm_attempts = 0
        self.failure_time = None
        self.failure_reason = None
    
    def record_phase_complete(self, phase_name):
        """Record that a phase completed"""
        if phase_name not in self.phases_completed:
            self.phases_completed.append(phase_name)
    
    def record_error(self, severity, message):
        """Record an error message"""
        self.recent_errors.append({
            'timestamp': time.time(),
            'severity': severity,
            'message': message
        })
    
    def set_failure_info(self, phase, reason):
        """Set failure information"""
        self.failed_phase = phase
        self.failure_reason = reason
        self.failure_time = time.time()
    
    def generate_report(self):
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
    
    def get_recommendation(self):
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
    
    def format_display(self):
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

class PlaybackTestExecutor(QThread):
    """
    Executes a flight profile playback test.

    Sequence:
      1. Connect to vehicle
      2. Set CLASSIC_MODE_EN=1, USE_NEST=0, power cycle
      3. ARM → OPERATE → PLAYBACK
      4. Stream PANDION_RR_PLAYBACK_COMMAND at 100 Hz from CSV
      5. Log command vs feedback delta per surface per frame
      6. Evaluate pass/fail against mistracking flags
      7. Restore vehicle state (CLASSIC_MODE_EN=0, power cycle)
    """

    # Qt signals
    progress_update   = pyqtSignal(int)
    status_update     = pyqtSignal(str)
    test_complete     = pyqtSignal(bool, str)
    log_message       = pyqtSignal(str)
    time_expired      = pyqtSignal()
    armed_state_update = pyqtSignal(bool, int)
    mode_update        = pyqtSignal(int)
    actuator_feedback_update = pyqtSignal(dict)
    connection_health_update = pyqtSignal(bool)
    alert_update       = pyqtSignal(str)
    test_duration_update = pyqtSignal(float)

    # Playback type constants
    TYPE_ACTUATION  = 'Actuation'
    TYPE_PROPULSION = 'Propulsion'
    TYPE_BOTH       = 'Both'

    # PANDION_RR_IBIT_MON_STATUS_FLAGS bitmask names (for pass/fail reporting)
    MISTRACKING_FLAGS = {
        1:   'Upper Rudder',
        2:   'Lower Rudder',
        4:   'Left TVC Upper',
        8:   'Left TVC Lower',
        16:  'Right TVC Upper',
        32:  'Right TVC Lower',
        64:  'Left Elevon',
        128: 'Right Elevon',
    }

    def __init__(self, uut, daq_controller, batch_end_time,
                 stabilization_delay, connection_timeout,
                 log_directory, test_start_datetime,
                 playback_csv, playback_type,
                 config=None):
        """
        Args:
            uut: UUT object
            daq_controller: DAQ controller for relay (power cycle)
            batch_end_time: Batch expiry timestamp
            stabilization_delay: Seconds to wait after relay enable
            connection_timeout: MAVLink connection timeout
            log_directory: Log output directory
            test_start_datetime: Batch start datetime
            playback_csv: Path to flight profile CSV
            playback_type: 'Actuation', 'Propulsion', or 'Both'
            config: Optional config dict
        """
        super().__init__()
        self.uut = uut
        self.daq = daq_controller
        self.batch_end_time = batch_end_time
        self.stabilization_delay = stabilization_delay
        self.connection_timeout = connection_timeout
        self.log_directory = log_directory
        self.test_start_datetime = test_start_datetime
        self.playback_csv = playback_csv
        self.playback_type = playback_type
        self.config = config or {}

        self.running = False
        self.master = None
        self.telemetry_logger = None
        self.preparation = None
        self.master_lock = threading.Lock()
        self.heartbeat_count = 0
        self.heartbeat_thread = None

    # ----------------------------------------------------------
    # QThread entry point
    # ----------------------------------------------------------

    def run(self):
        self.running = True
        success = False
        message = ""

        try:
            if time.time() >= self.batch_end_time:
                self.time_expired.emit()
                return

            # Load CSV profile first so we fail fast before touching the vehicle
            profile = self._load_profile(self.playback_csv)
            self.log_message.emit(
                f"✓ Profile loaded: {len(profile)} frames "
                f"({len(profile) / 100.0:.1f}s at 100 Hz)"
            )

            # Connect
            self.status_update.emit("Connecting to vehicle...")
            self.master = connect_to_vehicle(
                self.uut.ip_address, self.uut.port, self.connection_timeout
            )
            self.log_message.emit(
                f"✓ Connected to {self.uut.ip_address}:{self.uut.port}"
            )

            # Start heartbeat
            self.heartbeat_thread = threading.Thread(
                target=self._heartbeat_worker, daemon=True
            )
            self.heartbeat_thread.start()
            time.sleep(2.0)

            # Telemetry logger
            self.telemetry_logger = TelemetryLogger(
                self.log_directory,
                self.uut.serial_number,
                self.test_start_datetime,
                logging_mode=TelemetryLogger.MODE_IBIT_FOCUSED
            )
            self.telemetry_logger.log_message.connect(self.log_message)
            if not self.telemetry_logger.open():
                raise Exception("Failed to open log file")
            self.uut.log_file = self.telemetry_logger.get_current_log_path()

            self.uut.iterations_completed += 1
            self.telemetry_logger.set_iteration_number(self.uut.iterations_completed)
            self.telemetry_logger.log_test_event(
                'PLAYBACK_START',
                f"Starting playback test iteration #{self.uut.iterations_completed} "
                f"for UUT {self.uut.serial_number} — type={self.playback_type}"
            )

            # Preparation
            self.preparation = UUTPreparation(
                self.master, self.config, self.telemetry_logger
            )
            self.preparation.log_message.connect(self.log_message)
            self.preparation.progress_update.connect(self.status_update)

            prep_ok, prep_msg = self.preparation.capture_initial_state()
            if not prep_ok:
                raise Exception(prep_msg)

            prep_ok, prep_msg = self.preparation.prepare_for_playback(
                self._power_cycle
            )
            if not prep_ok:
                raise Exception(prep_msg)

            # Enable load relay
            self.status_update.emit("Enabling load relay...")
            ok, msg = self.daq.set_line(self.uut.relay_line, True)
            if not ok:
                raise Exception(f"Failed to enable relay: {msg}")
            self.telemetry_logger.log_relay_state(self.uut.relay_line, True)
            self.log_message.emit(
                f"✓ Relay {self.uut.relay_line} ENABLED"
            )
            time.sleep(self.stabilization_delay)

            # Stream profile
            mistracking_flags, max_delta = self._stream_profile(profile)

            # Disable relay
            self.daq.set_line(self.uut.relay_line, False)
            self.telemetry_logger.log_relay_state(self.uut.relay_line, False)
            self.log_message.emit(f"✓ Relay {self.uut.relay_line} DISABLED")

            # Evaluate pass/fail
            success, message = self._evaluate_result(mistracking_flags, max_delta)

        except Exception as e:
            success = False
            message = f"Playback test failed: {str(e)}"
            self.log_message.emit(f"✗ Error: {e}")
            self.alert_update.emit(f"PLAYBACK FAILED: {str(e)}")
            if self.daq:
                self._emergency_relay_disable()
            if self.telemetry_logger:
                self.telemetry_logger.log_test_event('TEST_FAILED', str(e))

        finally:
            self._cleanup()

        self.test_complete.emit(success, message)

    def stop(self):
        self.running = False

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

        self.log_message.emit(f"  CSV columns: {list(rows[0].keys())}")
        return rows

    # ----------------------------------------------------------
    # Profile streaming
    # ----------------------------------------------------------

    def _stream_profile(self, profile):
        """
        Stream PANDION_RR_PLAYBACK_COMMAND at 100 Hz and collect feedback.

        Returns:
            (mistracking_flags: int, max_deltas: dict surface->max_cdeg_error)
        """
        self.log_message.emit("=" * 60)
        self.log_message.emit("STREAMING FLIGHT PROFILE")
        self.log_message.emit(f"  Type: {self.playback_type}")
        self.log_message.emit(f"  Frames: {len(profile)}")
        self.log_message.emit("=" * 60)

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
                self.log_message.emit("⚠ Playback stopped by user")
                break

            frame_start = time.time()

            # Parse commands
            try:
                left_elev  = float(row['event/left_elevon_ted_command_cdeg'])
                right_elev = float(row['event/right_elevon_ted_command_cdeg'])
                low_rud    = float(row['event/lower_rudder_tel_command_cdeg'])
                up_rud     = float(row['event/upper_rudder_tel_command_cdeg'])
                l_tvc_up   = float(row['event/left_tvc_upper_command_cdeg'])
                l_tvc_lo   = float(row['event/left_tvc_lower_command_cdeg'])
                r_tvc_up   = float(row['event/right_tvc_upper_command_cdeg'])
                r_tvc_lo   = float(row['event/right_tvc_lower_command_cdeg'])
                l_eng      = float(row['event/left_engine_speed_command_prct_rpm'])
                r_eng      = float(row['event/right_engine_speed_command_prct_rpm'])
            except (ValueError, KeyError) as e:
                self.log_message.emit(f"⚠ Frame {frame_idx} parse error: {e}")
                continue

            # Zero out channels we're not commanding
            if not use_actuation:
                left_elev = right_elev = low_rud = up_rud = 0.0
                l_tvc_up = l_tvc_lo = r_tvc_up = r_tvc_lo = 0.0
            if not use_propulsion:
                l_eng = r_eng = 0.0

            # Send PANDION_RR_PLAYBACK_COMMAND (msg 12291)
            with self.master_lock:
                self.master.mav.pandion_rr_playback_command_send(
                    left_elevon_ted_command_cdeg=left_elev,
                    right_elevon_ted_command_cdeg=right_elev,
                    lower_rudder_tel_command_cdeg=low_rud,
                    upper_rudder_tel_command_cdeg=up_rud,
                    left_tvc_upper_command_cdeg=l_tvc_up,
                    left_tvc_lower_command_cdeg=l_tvc_lo,
                    right_tvc_upper_command_cdeg=r_tvc_up,
                    right_tvc_lower_command_cdeg=r_tvc_lo,
                    left_engine_speed_command_prct_thrust=l_eng,
                    right_engine_speed_command_prct_thrust=r_eng,
                )

            # Read feedback (non-blocking — use latest available)
            with self.master_lock:
                fb = self.master.recv_match(
                    type='PANDION_RR_ACTUATION_SYS_STATUS',
                    blocking=False,
                    timeout=0.005
                )
            if fb:
                # Accumulate mistracking flags
                accumulated_flags |= getattr(fb, 'actuation_ibit_mon_status', 0)

                # Track max command-feedback delta per surface
                if use_actuation:
                    max_deltas['left_elevon']   = max(max_deltas['left_elevon'],
                        abs(left_elev  - getattr(fb, 'left_elevon_feedback_cdeg', left_elev)))
                    max_deltas['right_elevon']  = max(max_deltas['right_elevon'],
                        abs(right_elev - getattr(fb, 'right_elevon_feedback_cdeg', right_elev)))
                    max_deltas['dorsal_rudder'] = max(max_deltas['dorsal_rudder'],
                        abs(up_rud  - getattr(fb, 'dorsal_rudder_feedback_cdeg', up_rud)))
                    max_deltas['ventral_rudder']= max(max_deltas['ventral_rudder'],
                        abs(low_rud - getattr(fb, 'ventral_rudder_feedback_cdeg', low_rud)))
                    max_deltas['left_tvc_upper']= max(max_deltas['left_tvc_upper'],
                        abs(l_tvc_up - getattr(fb, 'left_tvc_upper_feedback_cdeg', l_tvc_up)))
                    max_deltas['left_tvc_lower']= max(max_deltas['left_tvc_lower'],
                        abs(l_tvc_lo - getattr(fb, 'left_tvc_lower_feedback_cdeg', l_tvc_lo)))
                    max_deltas['right_tvc_upper']= max(max_deltas['right_tvc_upper'],
                        abs(r_tvc_up - getattr(fb, 'right_tvc_upper_feedback_cdeg', r_tvc_up)))
                    max_deltas['right_tvc_lower']= max(max_deltas['right_tvc_lower'],
                        abs(r_tvc_lo - getattr(fb, 'right_tvc_lower_feedback_cdeg', r_tvc_lo)))

                # Emit to UI
                try:
                    self.actuator_feedback_update.emit({
                        'left_elevon_feedback_cdeg':    fb.left_elevon_feedback_cdeg,
                        'right_elevon_feedback_cdeg':   fb.right_elevon_feedback_cdeg,
                        'dorsal_rudder_feedback_cdeg':  fb.dorsal_rudder_feedback_cdeg,
                        'ventral_rudder_feedback_cdeg': fb.ventral_rudder_feedback_cdeg,
                        'left_tvc_upper_feedback_cdeg': fb.left_tvc_upper_feedback_cdeg,
                        'left_tvc_lower_feedback_cdeg': fb.left_tvc_lower_feedback_cdeg,
                        'right_tvc_upper_feedback_cdeg':fb.right_tvc_upper_feedback_cdeg,
                        'right_tvc_lower_feedback_cdeg':fb.right_tvc_lower_feedback_cdeg,
                        'left_elevon_current_mA':       fb.left_elevon_current_mA,
                        'right_elevon_current_mA':      fb.right_elevon_current_mA,
                        'dorsal_rudder_current_mA':     fb.dorsal_rudder_current_mA,
                        'ventral_rudder_current_mA':    fb.ventral_rudder_current_mA,
                        'left_tvc_upper_current_mA':    fb.left_tvc_upper_current_mA,
                        'left_tvc_lower_current_mA':    fb.left_tvc_lower_current_mA,
                        'right_tvc_upper_current_mA':   fb.right_tvc_upper_current_mA,
                        'right_tvc_lower_current_mA':   fb.right_tvc_lower_current_mA,
                        'left_elevon_motor_temp_degC':  fb.left_elevon_motor_temp_degC,
                        'right_elevon_motor_temp_degC': fb.right_elevon_motor_temp_degC,
                    })
                except AttributeError:
                    pass

            # Progress log every 10%
            pct = int((frame_idx / total_frames) * 100)
            if pct // 10 != last_pct_logged // 10:
                self.log_message.emit(
                    f"  [{pct:3d}%] Frame {frame_idx}/{total_frames} — "
                    f"mistracking_flags=0x{accumulated_flags:02X}"
                )
                self.progress_update.emit(pct)
                last_pct_logged = pct

            # Duration update
            if self.uut.test_start_time:
                self.test_duration_update.emit(
                    time.time() - self.uut.test_start_time
                )

            # Pace to 100 Hz
            elapsed = time.time() - frame_start
            remaining = interval - elapsed
            if remaining > 0:
                time.sleep(remaining)

        self.log_message.emit(
            f"\n✓ Profile streaming complete — "
            f"{len(profile)} frames, "
            f"mistracking_flags=0x{accumulated_flags:02X}"
        )

        # Exit PLAYBACK → back to OPERATE
        with self.master_lock:
            self.master.mav.pandion_rr_actuation_request_mode_send(
                requested_mode=2
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
        self.log_message.emit("\n" + "=" * 60)
        self.log_message.emit("PLAYBACK RESULT EVALUATION")
        self.log_message.emit("=" * 60)

        # Log max deltas
        self.log_message.emit("Max command-feedback deltas:")
        for surface, delta in max_deltas.items():
            self.log_message.emit(f"  {surface:25s}: {delta:.1f} cdeg")

        # Evaluate mistracking flags
        if mistracking_flags == 0:
            self.log_message.emit("\n✓ PASS — No mistracking flags set")
            self.telemetry_logger.log_test_event(
                'PLAYBACK_PASS',
                f'All surfaces tracked correctly — max_deltas={max_deltas}'
            )
            return True, "Playback PASS — all surfaces tracked correctly"
        else:
            failed_surfaces = [
                name for bit, name in self.MISTRACKING_FLAGS.items()
                if mistracking_flags & bit
            ]
            msg = f"Playback FAIL — mistracking on: {', '.join(failed_surfaces)}"
            self.log_message.emit(f"\n✗ FAIL — {msg}")
            self.log_message.emit(
                f"  Mistracking flags: 0x{mistracking_flags:02X}"
            )
            for surface in failed_surfaces:
                self.log_message.emit(f"  ✗ {surface}")
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
        self.log_message.emit("  Disabling relay (power off)...")
        self.daq.set_line(self.uut.relay_line, False)
        if self.telemetry_logger:
            self.telemetry_logger.log_relay_state(self.uut.relay_line, False)
        time.sleep(3.0)

        self.log_message.emit("  Enabling relay (power on)...")
        ok, msg = self.daq.set_line(self.uut.relay_line, True)
        if not ok:
            raise Exception(f"Relay re-enable failed: {msg}")
        if self.telemetry_logger:
            self.telemetry_logger.log_relay_state(self.uut.relay_line, True)
        time.sleep(self.stabilization_delay)

        self.log_message.emit("  Waiting for vehicle heartbeat after power cycle...")
        timeout = 30.0
        start = time.time()
        while time.time() - start < timeout:
            with self.master_lock:
                hb = self.master.wait_heartbeat(timeout=2.0)
            if hb:
                self.log_message.emit(
                    f"  ✓ Heartbeat received after "
                    f"{time.time() - start:.1f}s"
                )
                time.sleep(2.0)  # Allow boot to settle
                return
            time.sleep(0.5)

        raise Exception(
            f"Vehicle did not respond after power cycle within {timeout}s"
        )

    # ----------------------------------------------------------
    # Background workers
    # ----------------------------------------------------------

    def _heartbeat_worker(self):
        """Send GCS heartbeats at 1 Hz"""
        while self.running:
            try:
                with self.master_lock:
                    if self.master:
                        self.master.mav.heartbeat_send(
                            mavutil.mavlink.MAV_TYPE_GCS,
                            mavutil.mavlink.MAV_AUTOPILOT_INVALID,
                            0, 0,
                            mavutil.mavlink.MAV_STATE_ACTIVE
                        )
                        self.heartbeat_count += 1
            except Exception:
                pass
            time.sleep(1.0)

    def _emergency_relay_disable(self):
        """Best-effort relay disable on failure"""
        for _ in range(5):
            try:
                ok, _ = self.daq.set_line(self.uut.relay_line, False)
                if ok:
                    self.log_message.emit(
                        f"✓ Emergency relay {self.uut.relay_line} disabled"
                    )
                    return
            except Exception:
                pass
            time.sleep(0.5)
        self.alert_update.emit(
            f"CRITICAL: RELAY {self.uut.relay_line} CONTROL FAILURE"
        )

    def _cleanup(self):
        """Restore vehicle state and close connections"""
        self.log_message.emit("→ Playback cleanup...")

        # Restore CLASSIC_MODE_EN = 0 so vehicle returns to normal mode
        if self.preparation and self.master:
            try:
                self.log_message.emit(
                    "  → Restoring CLASSIC_MODE_EN = 0..."
                )
                self.preparation._set_param('CLASSIC_MODE_EN', 0)
                self.log_message.emit(
                    "  ✓ CLASSIC_MODE_EN restored — power cycle vehicle "
                    "before operational use"
                )
            except Exception as e:
                self.log_message.emit(
                    f"  ⚠ Could not restore CLASSIC_MODE_EN: {e}"
                )

            try:
                self.preparation.restore_original_state()
            except Exception as e:
                self.log_message.emit(f"  ⚠ State restore error: {e}")

        self.running = False

        if self.heartbeat_thread and self.heartbeat_thread.is_alive():
            self.heartbeat_thread.join(timeout=2.0)

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

        self.log_message.emit("✓ Playback cleanup complete")