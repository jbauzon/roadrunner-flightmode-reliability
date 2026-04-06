"""
Vehicle Preparation - State capture and restoration

This module manages the complete vehicle preparation sequence:
1. Capture initial state
2. Prepare for test (ARM → OPERATE → PLAYBACK → IBIT)
3. Restore original state after test
4. Verify restoration
"""
import time
import threading
from pymavlink import mavutil
from PyQt5.QtCore import QObject, pyqtSignal
from .connection import UUTState


class UUTPreparation(QObject):
    """
    Handles UUT state capture, preparation, and restoration.
    
    Complete mode sequence: ARM → OPERATE → PLAYBACK → IBIT
    Then restoration after test complete.
    """
    
    log_message = pyqtSignal(str)
    progress_update = pyqtSignal(str)
    
    def __init__(self, master, config=None, telemetry_logger=None):
        """
        Initialize preparation manager.
        
        Args:
            master: MAVLink connection
            config: Configuration dictionary
            telemetry_logger: Optional logger for events
        """
        super().__init__()
        self.master = master
        self.config = config or {}
        self.telemetry_logger = telemetry_logger
        self.initial_state = UUTState()
        self.use_nest_cache = None
        self.master_lock = threading.Lock()
    
    def capture_initial_state(self):
        """
        Capture the initial state of the UUT.
        
        Queries:
        - USE_NEST parameter
        - Armed status (from PANDION_STATUS)
        - Actuation mode
        - SET monitors
        - Overridden monitors
        
        Returns:
            (success: bool, message: str)
        """
        self.log_message.emit("Step: Capturing initial state...")
        
        if self.telemetry_logger:
            self.telemetry_logger.log_test_event(
                'STATE_CAPTURE',
                'Capturing initial vehicle state before test'
            )
        
        self.initial_state = UUTState()
        self.initial_state.timestamp = time.time()
        
        try:
            # Query USE_NEST parameter
            self.progress_update.emit("Querying USE_NEST parameter...")
            use_nest = self._query_use_nest()
            
            if use_nest is None:
                self.log_message.emit(
                    "  ⚠ USE_NEST parameter not found (may not exist on this vehicle)"
                )
                self.initial_state.use_nest = 0
            else:
                self.initial_state.use_nest = use_nest
                self.log_message.emit(
                    f"  ✓ USE_NEST = {use_nest} "
                    f"({'ENABLED' if use_nest == 1 else 'DISABLED'})"
                )
            
            # Query actuation status
            self.progress_update.emit("Querying actuation status...")
            actuation_msg = self._wait_for_message(
                'PANDION_RR_ACTUATION_SYS_STATUS', 
                timeout=5.0
            )
            
            if not actuation_msg:
                raise Exception("Failed to receive actuation status")
            
            self.initial_state.actuation_mode = actuation_msg.actuation_state
            self.log_message.emit(
                f"  ✓ Actuation Mode = {actuation_msg.actuation_state}"
            )
            
            # Query armed state from PANDION_STATUS
            self.progress_update.emit("Querying armed state...")
            pandion_status = self._wait_for_message('PANDION_STATUS', timeout=5.0)
            
            if not pandion_status:
                raise Exception("Failed to receive PANDION_STATUS")
            
            flight_regime = pandion_status.flight_regime
            self.initial_state.flight_regime = flight_regime
            self.initial_state.armed = (flight_regime >= 1 and flight_regime != 255)
            
            # Log with flight regime name
            regime_names = {
                0: "GROUND_DISARMED", 1: "GROUND_ARMED", 2: "AUTO_TAKEOFF",
                3: "HOVER", 4: "FORWARD_TRANSITION", 5: "CRUISE",
                255: "INVALID"
            }
            regime_name = regime_names.get(flight_regime, f"REGIME_{flight_regime}")
            self.log_message.emit(f"  ✓ Flight Regime = {flight_regime} ({regime_name})")
            self.log_message.emit(f"  ✓ Armed = {self.initial_state.armed}")
            
            # Query monitor status
            self.progress_update.emit("Querying monitor status...")
            monitor_msg = self._wait_for_message(
                'PANDION_MONITOR_CURRENT_STATUS',
                timeout=5.0
            )
            
            if not monitor_msg:
                self.log_message.emit(
                    "  ⚠ Monitor status not available (may not exist on this vehicle)"
                )
                self.initial_state.set_monitors = []
                self.initial_state.overridden_monitors = []
            else:
                self.initial_state.set_monitors = self._extract_monitors_from_msg(
                    monitor_msg.currently_set
                )
                self.initial_state.overridden_monitors = self._extract_monitors_from_msg(
                    monitor_msg.currently_overridden
                )
                self.log_message.emit(
                    f"  ✓ SET Monitors: {len(self.initial_state.set_monitors)} monitor(s)"
                )
                self.log_message.emit(
                    f"  ✓ Overridden: {len(self.initial_state.overridden_monitors)} monitor(s)"
                )
            
            self.initial_state.captured = True
            
            self.log_message.emit("✓ Initial State Captured:")
            for line in self.initial_state.format_display().split('\n'):
                self.log_message.emit(f"  {line}")
            
            return True, "State captured successfully"
            
        except Exception as e:
            return False, f"State capture failed: {str(e)}"
    
    def prepare_for_playback(self, power_cycle_fn):
        """
        Prepare UUT for flight profile playback.

        Sequence:
          1. Set CLASSIC_MODE_EN = 1  (if not already)
          2. Set USE_NEST = 0         (if not already)
          3. Power cycle via relay    (required for CLASSIC_MODE_EN to take effect)
          4. Wait for reconnect
          5. ARM → OPERATE → PLAYBACK (stay in PLAYBACK — do NOT transition to IBIT)

        Args:
            power_cycle_fn: Callable() that power-cycles the vehicle via the relay
                            and waits until it is back online. Should raise on failure.

        Returns:
            (success: bool, message: str)
        """
        self.log_message.emit("═══════════════════════════════════════════")
        self.log_message.emit("PLAYBACK PRE-FLIGHT PREPARATION")
        self.log_message.emit("═══════════════════════════════════════════")

        try:
            # Step 1: Set CLASSIC_MODE_EN = 1
            self.log_message.emit("→ Setting CLASSIC_MODE_EN = 1...")
            success, msg = self._set_param('CLASSIC_MODE_EN', 1)
            if not success:
                raise Exception(f"Could not set CLASSIC_MODE_EN: {msg}")
            self.log_message.emit(f"  ✓ {msg}")

            # Step 2: Ensure USE_NEST = 0
            if self.initial_state.use_nest != 0:
                self.log_message.emit("→ Setting USE_NEST = 0...")
                success, msg = self._set_use_nest(0)
                if not success:
                    self.log_message.emit(f"  ⚠ Could not disable USE_NEST: {msg}")
                else:
                    self.log_message.emit(f"  ✓ {msg}")
            else:
                self.log_message.emit("✓ USE_NEST already 0, skipping")

            # Step 3: Power cycle (CLASSIC_MODE_EN only takes effect after reboot)
            self.log_message.emit(
                "\n→ Power cycling vehicle for CLASSIC_MODE_EN to take effect..."
            )
            if self.telemetry_logger:
                self.telemetry_logger.log_test_event(
                    'POWER_CYCLE',
                    'Power cycling vehicle for CLASSIC_MODE_EN to take effect'
                )
            power_cycle_fn()
            self.log_message.emit("  ✓ Power cycle complete, vehicle reconnected")

            # Step 4: ARM
            success, msg = self._arm_with_monitor_management()
            if not success:
                raise Exception(f"Failed to ARM: {msg}")
            self.log_message.emit(f"\n✓ {msg}")

            # Step 5: Wait for OPERATE
            self.log_message.emit("\n→ Waiting for OPERATE mode...")
            operate_timeout = 5.0
            operate_start = time.time()
            while time.time() - operate_start < operate_timeout:
                mode_msg = self._wait_for_message(
                    'PANDION_RR_ACTUATION_SYS_STATUS', timeout=1.0
                )
                if mode_msg and mode_msg.actuation_state == 2:
                    self.log_message.emit("  ✓ Vehicle in OPERATE mode")
                    break
                time.sleep(0.5)

            # Step 6: Clear monitors
            self.log_message.emit("\n→ Clearing monitors before PLAYBACK...")
            monitor_clear_duration = 5.0
            monitor_clear_start = time.time()
            while time.time() - monitor_clear_start < monitor_clear_duration:
                current_set = self._get_current_set_monitors()
                if current_set:
                    self._clear_specific_monitors(current_set)
                time.sleep(0.5)

            # Step 7: Enter PLAYBACK — stay here for profile streaming
            self.log_message.emit("\n→ Requesting PLAYBACK mode...")
            with self.master_lock:
                self.master.mav.pandion_rr_actuation_request_mode_send(
                    requested_mode=4
                )

            playback_timeout = 10.0
            playback_start = time.time()
            while time.time() - playback_start < playback_timeout:
                mode_msg = self._wait_for_message(
                    'PANDION_RR_ACTUATION_SYS_STATUS', timeout=0.5
                )
                if mode_msg and mode_msg.actuation_state == 4:
                    self.log_message.emit("  ✓ Vehicle in PLAYBACK mode")
                    break
                time.sleep(0.1)
            else:
                raise Exception("Failed to enter PLAYBACK mode")

            # Clear any monitors that appeared during PLAYBACK entry
            clear_start = time.time()
            while time.time() - clear_start < 3.0:
                current_set = self._get_current_set_monitors()
                if current_set:
                    self._clear_specific_monitors(current_set)
                time.sleep(0.5)

            self.log_message.emit("\n✓ Playback preparation complete — ready to stream profile")
            return True, "Playback preparation complete"

        except Exception as e:
            self.log_message.emit(f"\n✗ Playback preparation FAILED: {e}")
            return False, str(e)

    def _set_param(self, param_name, value):
        """
        Set a Pandion parameter by name with verification.

        Args:
            param_name: Parameter name string (max 16 chars)
            value: Integer or float value to set

        Returns:
            (success: bool, message: str)
        """
        try:
            param_bytes = param_name.encode('utf-8')
            param_bytes = param_bytes + b'\x00' * (16 - len(param_bytes))

            with self.master_lock:
                self.master.mav.param_set_send(
                    self.master.target_system,
                    self.master.target_component,
                    param_bytes,
                    float(value),
                    9  # MAV_PARAM_TYPE_UINT8
                )

            time.sleep(1.0)

            # Verify by reading back
            with self.master_lock:
                self.master.mav.param_request_read_send(
                    self.master.target_system,
                    self.master.target_component,
                    param_bytes,
                    -1
                )

            timeout = 5.0
            start = time.time()
            while time.time() - start < timeout:
                msg = self.master.recv_match(
                    type='PARAM_VALUE', blocking=False, timeout=0.1
                )
                if msg:
                    name = (
                        msg.param_id.decode('utf-8').rstrip('\x00')
                        if isinstance(msg.param_id, bytes)
                        else str(msg.param_id).rstrip('\x00')
                    )
                    if name == param_name:
                        actual = int(msg.param_value)
                        if actual == int(value):
                            return True, f"{param_name} = {actual}"
                        else:
                            return False, (
                                f"{param_name} verification failed "
                                f"(expected {value}, got {actual})"
                            )
                time.sleep(0.05)

            return False, f"{param_name} set sent but no verification response"

        except Exception as e:
            return False, f"Error setting {param_name}: {str(e)}"

    def prepare_for_test(self):
        """
        Prepare UUT for testing.
        
        Full sequence: ARM → OPERATE → clear monitors → PLAYBACK → IBIT
        
        Why PLAYBACK? Vehicle firmware requires OPERATE → PLAYBACK → IBIT.
        Direct OPERATE → IBIT is not permitted.
        
        Returns:
            (success: bool, message: str)
        """
        self.log_message.emit("═══════════════════════════════════════════")
        self.log_message.emit("PRE-FLIGHT PREPARATION")
        self.log_message.emit("═══════════════════════════════════════════")
        
        try:
            # Step 1: Disable USE_NEST if needed
            if self.initial_state.use_nest is not None:
                if self.initial_state.use_nest != 0:
                    self.progress_update.emit("Disabling USE_NEST...")
                    self.log_message.emit("→ Setting USE_NEST = 0 (DISABLE)")
                    
                    if self.telemetry_logger:
                        self.telemetry_logger.log_test_event(
                            'USE_NEST_DISABLE',
                            'Setting USE_NEST parameter to 0 (DISABLED)'
                        )
                    
                    success, msg = self._set_use_nest(0)
                    if not success:
                        self.log_message.emit(f"  ⚠ Could not disable USE_NEST: {msg}")
                    else:
                        self.log_message.emit(f"  ✓ {msg}")
                else:
                    self.log_message.emit("✓ USE_NEST already disabled, skipping")
            else:
                self.log_message.emit("✓ USE_NEST not available on this vehicle, skipping")
            
            # Step 2: ARM vehicle if needed
            if not self.initial_state.armed:
                success, msg = self._arm_with_monitor_management()
                if not success:
                    skip_arm = self.config.get('skip_arm_for_ibit', False)
                    if skip_arm:
                        self.log_message.emit(
                            f"\n⚠ ARM failed but 'skip_arm_for_ibit' enabled"
                        )
                        self.log_message.emit(
                            f"  → Proceeding to IBIT without ARM (may fail)"
                        )
                    else:
                        raise Exception(f"Failed to ARM: {msg}")
                else:
                    self.log_message.emit(f"\n✓ {msg}")
            else:
                self.log_message.emit("✓ Vehicle already armed, skipping")
            
            # Step 3: Wait for automatic transition to OPERATE mode
            self.log_message.emit("\n→ Waiting for vehicle to enter OPERATE mode...")
            self.progress_update.emit("Waiting for OPERATE mode...")
            
            if self.telemetry_logger:
                self.telemetry_logger.log_test_event(
                    'MODE_TRANSITION_WAIT',
                    'Waiting for automatic transition to OPERATE mode'
                )
            
            operate_timeout = 5.0
            operate_start = time.time()
            in_operate = False
            
            while time.time() - operate_start < operate_timeout:
                mode_msg = self._wait_for_message(
                    'PANDION_RR_ACTUATION_SYS_STATUS',
                    timeout=1.0
                )
                
                if mode_msg:
                    current_mode = mode_msg.actuation_state
                    if current_mode == 2:  # OPERATE
                        in_operate = True
                        self.log_message.emit(f"  ✓ Vehicle entered OPERATE mode")
                        
                        if self.telemetry_logger:
                            self.telemetry_logger.log_test_event(
                                'MODE_CHANGE',
                                'Vehicle automatically transitioned to OPERATE mode'
                            )
                        break
                    else:
                        mode_names = {
                            0: "OFF", 1: "IBIT", 2: "OPERATE",
                            3: "MANUAL", 4: "PLAYBACK", 5: "TRIM"
                        }
                        self.log_message.emit(
                            f"  Current mode: {current_mode} "
                            f"({mode_names.get(current_mode, 'UNKNOWN')})"
                        )
                
                time.sleep(0.5)
            
            if not in_operate:
                self.log_message.emit(
                    f"  ⚠ Vehicle did not enter OPERATE mode within {operate_timeout}s"
                )
                self.log_message.emit(f"  → Proceeding to clear monitors anyway...")
            
            # Step 4: Continuously clear monitors before PLAYBACK
            self.log_message.emit(
                "\n→ Continuously clearing monitors before PLAYBACK transition..."
            )
            self.progress_update.emit("Clearing monitors...")
            
            if self.telemetry_logger:
                self.telemetry_logger.log_test_event(
                    'MONITOR_CONTINUOUS_CLEAR',
                    'Starting continuous monitor clearing before PLAYBACK'
                )
            
            monitor_clear_duration = 5.0
            monitor_clear_start = time.time()
            clear_count = 0
            
            while time.time() - monitor_clear_start < monitor_clear_duration:
                current_set = self._get_current_set_monitors()
                
                if len(current_set) > 0:
                    clear_count += 1
                    self.log_message.emit(
                        f"  [{clear_count}] Clearing {len(current_set)} "
                        f"SET monitors: {current_set}"
                    )
                    all_cleared, remaining = self._clear_specific_monitors(current_set)
                    
                    if not all_cleared:
                        self.log_message.emit(
                            f"    ⚠ {len(remaining)} monitors couldn't be cleared"
                        )
                else:
                    self.log_message.emit(f"  ✓ No SET monitors detected")
                
                time.sleep(0.5)
            
            self.log_message.emit(
                f"  ✓ Monitor clearing complete ({clear_count} clear operations)"
            )
            
            # Final monitor check
            final_set_monitors = self._get_current_set_monitors()
            if final_set_monitors:
                self.log_message.emit(
                    f"  ⚠ Warning: {len(final_set_monitors)} monitors still SET: "
                    f"{final_set_monitors}"
                )
            else:
                self.log_message.emit(f"  ✓ All monitors clear")
            
            # Step 5: Request transition to PLAYBACK mode
            self.log_message.emit("\n→ Requesting transition: OPERATE → PLAYBACK...")
            self.progress_update.emit("Entering PLAYBACK mode...")
            
            if self.telemetry_logger:
                self.telemetry_logger.log_test_event(
                    'PLAYBACK_REQUEST',
                    'Requesting transition from OPERATE to PLAYBACK mode'
                )
            
            self.log_message.emit(f"  Sending PLAYBACK mode request (mode 4)...")
            with self.master_lock:
                self.master.mav.pandion_rr_actuation_request_mode_send(requested_mode=4)
            
            # Monitor for PLAYBACK mode entry
            playback_timeout = 10.0
            playback_start = time.time()
            entered_playback = False
            
            self.log_message.emit(
                f"  Monitoring mode for up to {playback_timeout:.0f} seconds..."
            )
            
            while time.time() - playback_start < playback_timeout:
                mode_msg = self._wait_for_message(
                    'PANDION_RR_ACTUATION_SYS_STATUS',
                    timeout=0.5
                )
                
                if mode_msg:
                    current_mode = mode_msg.actuation_state
                    mode_names = {
                        0: "OFF", 1: "IBIT", 2: "OPERATE",
                        3: "MANUAL", 4: "PLAYBACK", 5: "TRIM"
                    }
                    
                    if current_mode == 4:  # PLAYBACK
                        elapsed = time.time() - playback_start
                        self.log_message.emit(
                            f"  ✓ Vehicle entered PLAYBACK mode after {elapsed:.1f} seconds"
                        )
                        
                        if self.telemetry_logger:
                            self.telemetry_logger.log_test_event(
                                'PLAYBACK_ENTERED',
                                f'Vehicle entered PLAYBACK mode successfully '
                                f'after {elapsed:.1f} seconds'
                            )
                        
                        entered_playback = True
                        break
                    else:
                        elapsed = time.time() - playback_start
                        if int(elapsed) % 2 == 0 and elapsed > 0:
                            mode_str = mode_names.get(
                                current_mode,
                                f"UNKNOWN({current_mode})"
                            )
                            self.log_message.emit(
                                f"    [{elapsed:.0f}s] Current mode: {mode_str}, "
                                f"waiting for PLAYBACK..."
                            )
                
                time.sleep(0.1)
            
            if not entered_playback:
                final_mode_msg = self._wait_for_message(
                    'PANDION_RR_ACTUATION_SYS_STATUS',
                    timeout=2.0
                )
                final_mode = final_mode_msg.actuation_state if final_mode_msg else -1
                mode_names = {
                    0: "OFF", 1: "IBIT", 2: "OPERATE",
                    3: "MANUAL", 4: "PLAYBACK", 5: "TRIM"
                }
                final_mode_str = mode_names.get(final_mode, f"UNKNOWN({final_mode})")
                
                if self.telemetry_logger:
                    self.telemetry_logger.log_test_event(
                        'PLAYBACK_FAILED',
                        f'Failed to enter PLAYBACK mode - stuck in {final_mode_str}'
                    )
                
                raise Exception(
                    f"Failed to enter PLAYBACK mode after {playback_timeout:.0f} seconds.\n"
                    f"  Current mode: {final_mode} ({final_mode_str})\n"
                    f"  Expected: 4 (PLAYBACK)\n"
                    f"  The vehicle may have conditions preventing PLAYBACK mode entry."
                )
            
            # Step 6: Continue clearing monitors in PLAYBACK
            self.log_message.emit(
                "\n→ Continuously clearing monitors in PLAYBACK before IBIT..."
            )
            self.progress_update.emit("Clearing monitors in PLAYBACK...")
            
            if self.telemetry_logger:
                self.telemetry_logger.log_test_event(
                    'MONITOR_PLAYBACK_CLEAR',
                    'Clearing monitors in PLAYBACK mode before IBIT'
                )
            
            playback_monitor_clear_duration = 3.0
            playback_clear_start = time.time()
            playback_clear_count = 0
            
            while time.time() - playback_clear_start < playback_monitor_clear_duration:
                current_set = self._get_current_set_monitors()
                
                if len(current_set) > 0:
                    playback_clear_count += 1
                    self.log_message.emit(
                        f"  [PLAYBACK-{playback_clear_count}] Clearing "
                        f"{len(current_set)} SET monitors: {current_set}"
                    )
                    all_cleared, remaining = self._clear_specific_monitors(current_set)
                    
                    if not all_cleared:
                        self.log_message.emit(
                            f"    ⚠ {len(remaining)} monitors couldn't be cleared"
                        )
                else:
                    self.log_message.emit(f"  ✓ No SET monitors in PLAYBACK")
                
                time.sleep(0.5)
            
            self.log_message.emit(
                f"  ✓ PLAYBACK monitor clearing complete "
                f"({playback_clear_count} clear operations)"
            )
            
            # Final monitor check before IBIT
            final_set_before_ibit = self._get_current_set_monitors()
            if final_set_before_ibit:
                self.log_message.emit(
                    f"  ⚠ Warning: {len(final_set_before_ibit)} monitors still SET "
                    f"before IBIT: {final_set_before_ibit}"
                )
                
                if self.telemetry_logger:
                    self.telemetry_logger.log_test_event(
                        'MONITOR_WARNING',
                        f'{len(final_set_before_ibit)} monitors still SET before IBIT: '
                        f'{final_set_before_ibit}'
                    )
            else:
                self.log_message.emit(f"  ✓ All monitors clear before IBIT")
            
            # Step 7: Request transition from PLAYBACK to IBIT
            self.log_message.emit("\n→ Requesting transition: PLAYBACK → IBIT...")
            self.progress_update.emit("Entering IBIT mode...")
            
            if self.telemetry_logger:
                self.telemetry_logger.log_test_event(
                    'IBIT_REQUEST',
                    'Requesting transition from PLAYBACK to IBIT mode'
                )
            
            # Send the request ONCE
            self.log_message.emit(f"  Sending IBIT mode request (mode 1)...")
            with self.master_lock:
                self.master.mav.pandion_rr_actuation_request_mode_send(requested_mode=1)
            
            # Monitor for IBIT mode entry
            timeout = 30.0
            check_interval = 0.5
            start_time = time.time()
            entered_ibit = False
            
            self.log_message.emit(f"  Monitoring mode for up to {timeout:.0f} seconds...")
            
            while time.time() - start_time < timeout:
                mode_msg = self._wait_for_message(
                    'PANDION_RR_ACTUATION_SYS_STATUS',
                    timeout=check_interval
                )
                
                if mode_msg:
                    current_mode = mode_msg.actuation_state
                    mode_names = {
                        0: "OFF", 1: "IBIT", 2: "OPERATE",
                        3: "MANUAL", 4: "PLAYBACK", 5: "TRIM"
                    }
                    
                    if current_mode == 1:  # IBIT
                        elapsed = time.time() - start_time
                        self.log_message.emit(
                            f"  ✓ Vehicle entered IBIT mode after {elapsed:.1f} seconds"
                        )
                        
                        if self.telemetry_logger:
                            self.telemetry_logger.log_test_event(
                                'IBIT_ENTERED',
                                f'Vehicle entered IBIT mode successfully '
                                f'after {elapsed:.1f} seconds'
                            )
                        
                        entered_ibit = True
                        break
                    else:
                        elapsed = time.time() - start_time
                        if int(elapsed) % 5 == 0 and elapsed > 0:
                            mode_str = mode_names.get(
                                current_mode,
                                f"UNKNOWN({current_mode})"
                            )
                            self.log_message.emit(
                                f"    [{elapsed:.0f}s] Current mode: {mode_str}, "
                                f"waiting for IBIT..."
                            )
                
                time.sleep(0.1)
            
            if not entered_ibit:
                final_mode_msg = self._wait_for_message(
                    'PANDION_RR_ACTUATION_SYS_STATUS',
                    timeout=2.0
                )
                final_mode = final_mode_msg.actuation_state if final_mode_msg else -1
                mode_names = {
                    0: "OFF", 1: "IBIT", 2: "OPERATE",
                    3: "MANUAL", 4: "PLAYBACK", 5: "TRIM"
                }
                final_mode_str = mode_names.get(final_mode, f"UNKNOWN({final_mode})")
                
                if self.telemetry_logger:
                    self.telemetry_logger.log_test_event(
                        'IBIT_FAILED',
                        f'Failed to enter IBIT mode - stuck in {final_mode_str}'
                    )
                
                raise Exception(
                    f"Failed to enter IBIT mode after {timeout:.0f} seconds.\n"
                    f"  Current mode: {final_mode} ({final_mode_str})\n"
                    f"  Expected: 1 (IBIT)\n"
                    f"  The vehicle may have conditions preventing IBIT mode entry."
                )
            
            self.log_message.emit("\n✓ Pre-flight preparation complete")
            self.log_message.emit(
                "  Sequence: ARM → OPERATE → Clear Monitors → "
                "PLAYBACK → Clear Monitors → IBIT ✓"
            )
            
            return True, "Preparation complete"
            
        except Exception as e:
            self.log_message.emit(f"\n✗ Pre-flight preparation FAILED: {e}")
            return False, str(e)
    
    def restore_original_state(self):
        """
        Restore UUT to original state.
        
        Sequence:
        1. Ensure OPERATE mode
        2. Clear overridden monitors BEFORE disarm
        3. DISARM if needed
        4. Transition to OFF mode
        
        Returns:
            (success: bool, message: str)
        """
        self.log_message.emit("═══════════════════════════════════════════")
        self.log_message.emit("POST-FLIGHT RESTORATION")
        self.log_message.emit("═══════════════════════════════════════════")
        
        if self.telemetry_logger:
            self.telemetry_logger.log_test_event(
                'RESTORATION_START',
                'Starting restoration to original vehicle state'
            )
        
        if not self.initial_state.captured:
            self.log_message.emit("⚠ No initial state captured, cannot restore.")
            return False, "No initial state"
        
        self.log_message.emit("Target State (from initial capture):")
        for line in self.initial_state.format_display().split('\n'):
            self.log_message.emit(f"  {line}")
        
        try:
            # Step 1: Ensure we're in OPERATE mode first
            current_mode_msg = self._wait_for_message(
                'PANDION_RR_ACTUATION_SYS_STATUS',
                timeout=3.0
            )
            current_mode = current_mode_msg.actuation_state if current_mode_msg else -1
            
            if current_mode == 1:  # Still in IBIT
                self.log_message.emit(
                    f"⚠ Still in IBIT mode, requesting OPERATE first..."
                )
                with self.master_lock:
                    self.master.mav.pandion_rr_actuation_request_mode_send(
                        requested_mode=2
                    )
                time.sleep(3.0)
                
                verify_msg = self._wait_for_message(
                    'PANDION_RR_ACTUATION_SYS_STATUS',
                    timeout=3.0
                )
                if verify_msg and verify_msg.actuation_state == 2:
                    self.log_message.emit(f"  ✓ Vehicle in OPERATE mode")
                else:
                    self.log_message.emit(f"  ⚠ Could not transition to OPERATE")
            
            elif current_mode == 2:
                self.log_message.emit(f"✓ Vehicle already in OPERATE mode")
            else:
                self.log_message.emit(f"⚠ Unexpected mode: {current_mode}")
            
            time.sleep(1.0)
            
            # Step 2: Clear overridden monitors BEFORE disarming
            self.log_message.emit("\n→ Clearing overridden monitors BEFORE disarm...")
            current_overridden = self._get_current_overridden_monitors()
            
            if current_overridden:
                self.log_message.emit(
                    f"  Found {len(current_overridden)} overridden monitors: "
                    f"{current_overridden}"
                )
                
                if self.telemetry_logger:
                    self.telemetry_logger.log_test_event(
                        'MONITOR_RESTORE_PRE_DISARM',
                        f'Clearing {len(current_overridden)} overridden monitors '
                        f'BEFORE disarm: {current_overridden}'
                    )
                
                with self.master_lock:
                    for mid in current_overridden:
                        self.master.mav.pandion_monitor_override_cmd_send(0, mid)
                        time.sleep(0.01)
                
                time.sleep(2.0)
                
                verify_overridden = self._get_current_overridden_monitors()
                if verify_overridden:
                    self.log_message.emit(
                        f"  ⚠ {len(verify_overridden)} monitors still overridden: "
                        f"{verify_overridden}"
                    )
                else:
                    self.log_message.emit(f"  ✓ All monitors cleared before disarm")
            else:
                self.log_message.emit(f"  ✓ No overridden monitors to clear")
            
            # Step 3: Disarm if needed
            if not self.initial_state.armed:
                pandion_status = self._wait_for_message('PANDION_STATUS', timeout=3.0)
                
                if pandion_status:
                    flight_regime = pandion_status.flight_regime
                    is_armed = (flight_regime >= 1 and flight_regime != 255)
                    
                    if is_armed:
                        self.log_message.emit(
                            f"\n→ Disarming vehicle (current flight regime: "
                            f"{flight_regime})..."
                        )
                        
                        if self.telemetry_logger:
                            self.telemetry_logger.log_test_event(
                                'DISARM_REQUEST',
                                'Sending DISARM command with improved retry'
                            )
                        
                        success, message = self._disarm_with_improved_retry(
                            max_attempts=5
                        )
                        
                        if success:
                            self.log_message.emit(f"  ✓ {message}")
                        else:
                            self.log_message.emit(f"  ⚠ {message}")
                            if self.telemetry_logger:
                                self.telemetry_logger.log_test_event(
                                    'DISARM_FAILED',
                                    message
                                )
                    else:
                        self.log_message.emit(f"✓ Vehicle already disarmed")
            
            time.sleep(2.0)
            
            # Step 4: Transition to OFF mode
            self.log_message.emit("\n→ Requesting transition to OFF mode...")
            with self.master_lock:
                self.master.mav.pandion_rr_actuation_request_mode_send(requested_mode=0)
            
            time.sleep(3.0)
            
            final_mode_msg = self._wait_for_message(
                'PANDION_RR_ACTUATION_SYS_STATUS',
                timeout=3.0
            )
            
            if final_mode_msg:
                final_mode = final_mode_msg.actuation_state
                mode_names = {
                    0: "OFF", 1: "IBIT", 2: "OPERATE",
                    3: "MANUAL", 4: "PLAYBACK", 5: "TRIM"
                }
                mode_str = mode_names.get(final_mode, f"UNKNOWN({final_mode})")
                
                if final_mode == 0:
                    self.log_message.emit(
                        f"✓ Final actuation mode: {final_mode} ({mode_str}) ✓"
                    )
                else:
                    self.log_message.emit(
                        f"⚠ Final actuation mode: {final_mode} ({mode_str}) - "
                        f"expected OFF"
                    )
                
                if self.telemetry_logger:
                    self.telemetry_logger.log_test_event(
                        'MODE_CHECK',
                        f'Final mode after restoration: {mode_str}'
                    )
            else:
                self.log_message.emit(f"⚠ Could not verify final mode")
            
            return True, "Restoration complete"
            
        except Exception as e:
            self.log_message.emit(f"✗ Restoration error: {e}")
            return False, str(e)
    
    def verify_final_state(self, relay_was_disabled=False):
        """
        Capture and verify final state matches initial.
        
        Args:
            relay_was_disabled: If True, skip verification (vehicle powered off)
        """
        self.log_message.emit("═══════════════════════════════════════════")
        self.log_message.emit("FINAL STATE VERIFICATION")
        self.log_message.emit("═══════════════════════════════════════════")
        
        # Skip verification if relay was disabled (vehicle is powered off)
        if relay_was_disabled:
            self.log_message.emit("⚠ Relay was disabled - skipping state verification")
            self.log_message.emit("  Reason: Cannot query vehicle state without power")
            self.log_message.emit("  Result: Vehicle is in safe powered-off state ✓")
            
            if self.telemetry_logger:
                self.telemetry_logger.log_test_event(
                    'STATE_VERIFICATION_SKIPPED',
                    'Relay disabled - vehicle powered off, cannot query final state'
                )
            return
        
        final_state = UUTState()
        success, _ = self._capture_current_state(final_state)
        
        if not success:
            self.log_message.emit("✗ Failed to capture final state for verification.")
            return
        
        self.log_message.emit("Final State After Restoration:")
        for line in final_state.format_display().split('\n'):
            self.log_message.emit(f"  {line}")
        
        if self.initial_state.matches(final_state):
            self.log_message.emit("✓✓✓ STATE SUCCESSFULLY RESTORED TO ORIGINAL ✓✓✓")
            
            if self.telemetry_logger:
                self.telemetry_logger.log_test_event(
                    'STATE_VERIFIED',
                    'Final state matches initial state - restoration successful'
                )
        else:
            differences = self.initial_state.get_differences(final_state)
            self.log_message.emit("⚠⚠⚠ STATE RESTORATION MISMATCH ⚠⚠⚠")
            
            for diff in differences:
                self.log_message.emit(f"  ⚠ {diff}")
            
            if self.telemetry_logger:
                self.telemetry_logger.log_test_event(
                    'STATE_MISMATCH',
                    f'State restoration mismatch detected: {"; ".join(differences)}'
                )
    
    # ========== HELPER METHODS ==========
    
    def _arm_with_monitor_management(self):
        """
        ARM vehicle: check monitors → clear → try ARM → repeat until success.
        
        Returns:
            (success: bool, message: str)
        """
        self.progress_update.emit("Arming vehicle with monitor management...")
        self.log_message.emit(
            "→ Attempting to ARM vehicle with iterative monitor management..."
        )
        
        if self.telemetry_logger:
            self.telemetry_logger.log_test_event(
                'ARM_REQUEST',
                'Starting ARM sequence with monitor management'
            )
        
        arm_timeout = self.config.get('arm_timeout', 60.0)
        max_iterations = self.config.get('max_arm_iterations', 20)
        
        start_time = time.time()
        iteration = 0
        
        while iteration < max_iterations and (time.time() - start_time) < arm_timeout:
            iteration += 1
            self.log_message.emit(f"\n  Iteration {iteration}/{max_iterations}:")
            
            # Check monitors
            self.log_message.emit(f"    Checking monitor status...")
            current_set = self._get_current_set_monitors()
            
            if len(current_set) > 0:
                self.log_message.emit(
                    f"    Found {len(current_set)} SET monitors: {current_set}"
                )
                all_cleared, remaining = self._clear_specific_monitors(current_set)
                
                if not all_cleared:
                    self.log_message.emit(
                        f"    ⚠ Some monitors couldn't be cleared (may be hardware faults)"
                    )
            else:
                self.log_message.emit(f"    ✓ No SET monitors")
            
            # Try ARM
            self.log_message.emit(f"    Attempting ARM command...")
            arm_success, arm_message = self._try_arm_once()
            
            if arm_success:
                self.log_message.emit(f"    ✓ Vehicle ARMED successfully!")
                self.log_message.emit(f"  Success on iteration {iteration}")
                
                if self.telemetry_logger:
                    self.telemetry_logger.log_test_event(
                        'ARM_SUCCESS',
                        f'Vehicle ARMED successfully after {iteration} iteration(s)'
                    )
                
                return True, f"Vehicle ARMED (iterations: {iteration})"
            else:
                self.log_message.emit(f"    ✗ ARM failed: {arm_message}")
            
            time.sleep(0.5)
            
            # Check what happened
            post_arm_set = self._get_current_set_monitors()
            if post_arm_set:
                self.log_message.emit(
                    f"    → After ARM failure, {len(post_arm_set)} monitors are SET"
                )
            else:
                self.log_message.emit(
                    f"    → No new monitors SET, but ARM still failed"
                )
            
            time.sleep(0.3)
        
        # ARM failed
        self.log_message.emit(f"\n✗ ARM FAILED after {iteration} iterations")
        final_set = self._get_current_set_monitors()
        
        if self.telemetry_logger:
            self.telemetry_logger.log_test_event(
                'ARM_FAILED',
                f'ARM failed after {iteration} iterations - '
                f'{len(final_set)} monitors cannot be cleared'
            )
        
        if final_set:
            self.log_message.emit(
                f"  Final status: {len(final_set)} monitors still SET: {final_set}"
            )
            self.log_message.emit(
                f"  These monitors could not be cleared - likely hardware faults"
            )
            return False, (
                f"ARM failed - {len(final_set)} monitors cannot be cleared "
                f"(hardware faults)"
            )
        else:
            self.log_message.emit(f"  Final status: No monitors SET, but ARM still failed")
            return False, "ARM failed - no monitors SET but vehicle refuses to ARM"
    
    def _try_arm_once(self):
        """
        Try to ARM vehicle once.
        
        Returns:
            (success: bool, message: str)
        """
        with self.master_lock:
            self.master.mav.command_long_send(
                self.master.target_system, 1,
                mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
                0, 1, 0, 0, 0, 0, 0, 0
            )
        
        # Wait for ACK
        ack = self._wait_for_message('COMMAND_ACK', timeout=2.0)
        
        if ack and ack.command == mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM:
            result_names = {
                0: "ACCEPTED", 1: "TEMPORARILY_REJECTED", 2: "DENIED",
                3: "UNSUPPORTED", 4: "FAILED", 5: "IN_PROGRESS"
            }
            result_str = result_names.get(ack.result, f"UNKNOWN({ack.result})")
            
            if ack.result == 0:  # ACCEPTED
                time.sleep(0.3)
                
                # Verify with PANDION_STATUS
                pandion_status = self._wait_for_message('PANDION_STATUS', timeout=2.0)
                if pandion_status:
                    flight_regime = pandion_status.flight_regime
                    is_armed = (flight_regime >= 1 and flight_regime != 255)
                    
                    if is_armed:
                        return True, "ARMED"
                    else:
                        return False, (
                            f"ACK received but not armed (flight regime: {flight_regime})"
                        )
            else:
                return False, result_str
        else:
            return False, "No ACK received"
    
    def _disarm_with_improved_retry(self, max_attempts=5):
        """
        Improved disarm with better ACK handling and longer timeouts.
        
        Args:
            max_attempts: Maximum number of DISARM attempts
        
        Returns:
            (success: bool, message: str)
        """
        for attempt in range(1, max_attempts + 1):
            self.log_message.emit(f"  DISARM attempt {attempt}/{max_attempts}...")
            
            with self.master_lock:
                self.master.mav.command_long_send(
                    self.master.target_system, 1,
                    mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
                    0, 0, 0, 0, 0, 0, 0, 0
                )
            
            # Wait for ACK with longer timeout
            timeout = 5.0
            start_time = time.time()
            ack_received = False
            
            while time.time() - start_time < timeout:
                ack = self._wait_for_message('COMMAND_ACK', timeout=0.5)
                
                if ack and ack.command == mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM:
                    ack_received = True
                    
                    if ack.result == 0:  # ACCEPTED
                        self.log_message.emit(f"    ✓ DISARM command accepted")
                        
                        # Wait for actual disarm (vehicle takes time)
                        time.sleep(2.0)
                        
                        # Verify with multiple checks
                        for verify_attempt in range(5):
                            ps = self._wait_for_message('PANDION_STATUS', timeout=1.0)
                            if ps:
                                if ps.flight_regime == 0:
                                    self.log_message.emit(
                                        f"    ✓ DISARMED verified (flight regime 0)"
                                    )
                                    
                                    if self.telemetry_logger:
                                        self.telemetry_logger.log_test_event(
                                            'DISARM_SUCCESS',
                                            f'Vehicle DISARMED on attempt {attempt}'
                                        )
                                    
                                    return True, f"DISARMED on attempt {attempt}"
                                else:
                                    self.log_message.emit(
                                        f"    ⚠ Still armed (flight regime: "
                                        f"{ps.flight_regime}), waiting..."
                                    )
                                    time.sleep(0.5)
                            else:
                                self.log_message.emit(
                                    f"    ⚠ No PANDION_STATUS received"
                                )
                                time.sleep(0.5)
                        
                        self.log_message.emit(
                            f"    ✗ DISARM accepted but verification failed"
                        )
                    else:
                        result_names = {
                            0: "ACCEPTED", 1: "TEMPORARILY_REJECTED", 2: "DENIED",
                            3: "UNSUPPORTED", 4: "FAILED", 5: "IN_PROGRESS"
                        }
                        result_str = result_names.get(ack.result, f"UNKNOWN({ack.result})")
                        self.log_message.emit(f"    ✗ DISARM rejected: {result_str}")
                    
                    break
                
                time.sleep(0.1)
            
            if not ack_received:
                self.log_message.emit(f"    ✗ No ACK received within {timeout}s")
            
            # Wait before retry
            if attempt < max_attempts:
                wait_time = min(attempt * 2, 5)
                self.log_message.emit(f"    → Retrying in {wait_time}s...")
                time.sleep(wait_time)
        
        return False, f"DISARM failed after {max_attempts} attempts"
    
    def _clear_specific_monitors(self, monitor_ids):
        """
        Clear only the specific monitors that are SET.
        
        Args:
            monitor_ids: List of monitor IDs to clear
        
        Returns:
            (all_cleared: bool, still_set: list)
        """
        if not monitor_ids:
            return True, []
        
        self.log_message.emit(
            f"    Clearing {len(monitor_ids)} monitors: {monitor_ids}"
        )
        
        if self.telemetry_logger:
            self.telemetry_logger.log_test_event(
                'MONITOR_CLEAR',
                f'Clearing {len(monitor_ids)} safety monitors: {monitor_ids}'
            )
        
        with self.master_lock:
            for monitor_id in monitor_ids:
                self.master.mav.pandion_monitor_override_cmd_send(2, monitor_id)
                time.sleep(0.01)
        
        time.sleep(1.5)
        
        # Verify
        verify_msg = self._wait_for_message(
            'PANDION_MONITOR_CURRENT_STATUS',
            timeout=2.0
        )
        
        if not verify_msg:
            return False, monitor_ids
        
        still_set = self._extract_monitors_from_msg(verify_msg.currently_set)
        cleared = set(monitor_ids) - set(still_set)
        
        if cleared:
            self.log_message.emit(
                f"    ✓ Cleared {len(cleared)} monitors: {sorted(list(cleared))}"
            )
        
        if still_set:
            self.log_message.emit(
                f"    ✗ {len(still_set)} monitors remain SET: {still_set}"
            )
        else:
            self.log_message.emit(f"    ✓ All monitors cleared")
        
        return len(still_set) == 0, still_set
    
    def _get_current_set_monitors(self):
        """Get list of currently SET monitors"""
        monitor_msg = self._wait_for_message(
            'PANDION_MONITOR_CURRENT_STATUS',
            timeout=2.0
        )
        
        if not monitor_msg:
            return []
        
        return self._extract_monitors_from_msg(monitor_msg.currently_set)
    
    def _get_current_overridden_monitors(self):
        """Get list of currently overridden monitors"""
        monitor_msg = self._wait_for_message(
            'PANDION_MONITOR_CURRENT_STATUS',
            timeout=3.0
        )
        
        return self._extract_monitors_from_msg(
            monitor_msg.currently_overridden
        ) if monitor_msg else []
    
    def _extract_monitors_from_msg(self, byte_array):
        """Extract monitor IDs from byte array"""
        monitors = []
        for byte_idx, byte_val in enumerate(byte_array):
            for bit in range(8):
                if byte_val & (1 << bit):
                    monitors.append(byte_idx * 8 + bit)
        return monitors
    
    def _query_use_nest(self):
        """Query USE_NEST parameter with caching"""
        if self.use_nest_cache is not None:
            return self.use_nest_cache
        
        try:
            # Clear receive buffer
            while True:
                msg = self.master.recv_match(
                    type='PARAM_VALUE',
                    blocking=False,
                    timeout=0.01
                )
                if not msg:
                    break
            
            # Request parameter
            param_id_bytes = b'USE_NEST' + b'\x00' * (16 - len(b'USE_NEST'))
            
            with self.master_lock:
                self.master.mav.param_request_read_send(
                    self.master.target_system,
                    self.master.target_component,
                    param_id_bytes,
                    -1
                )
            
            # Wait for response
            timeout = 5.0
            start_time = time.time()
            
            while time.time() - start_time < timeout:
                msg = self.master.recv_match(
                    type='PARAM_VALUE',
                    blocking=False,
                    timeout=0.1
                )
                
                if msg:
                    if isinstance(msg.param_id, bytes):
                        param_name = msg.param_id.decode('utf-8').rstrip('\x00')
                    else:
                        param_name = str(msg.param_id).rstrip('\x00')
                    
                    if param_name == 'USE_NEST':
                        value = int(msg.param_value)
                        self.log_message.emit(f"  ✓ Received USE_NEST = {value}")
                        self.use_nest_cache = value
                        return value
                
                time.sleep(0.05)
            
            self.log_message.emit("  ⚠ USE_NEST query timeout after 5s")
            return None
            
        except Exception as e:
            self.log_message.emit(f"  ⚠ Error querying USE_NEST: {e}")
            return None
    
    def _set_use_nest(self, value):
        """Set USE_NEST parameter with verification"""
        try:
            param_id_bytes = b'USE_NEST' + b'\x00' * (16 - len(b'USE_NEST'))
            
            with self.master_lock:
                self.master.mav.param_set_send(
                    self.master.target_system,
                    self.master.target_component,
                    param_id_bytes,
                    float(value),
                    mavutil.mavlink.MAV_PARAM_TYPE_UINT8
                )
            
            time.sleep(1.0)
            
            # Verify
            self.use_nest_cache = None
            actual = self._query_use_nest()
            
            if actual == value:
                return True, f"USE_NEST set to {value}"
            elif actual is None:
                return False, (
                    f"USE_NEST set command sent, but could not verify (query failed)"
                )
            else:
                return False, (
                    f"USE_NEST verification failed (expected {value}, got {actual})"
                )
                
        except Exception as e:
            return False, f"Error setting USE_NEST: {str(e)}"
    
    def _capture_current_state(self, state_obj):
        """Helper to capture the current state into a state object"""
        state_obj.timestamp = time.time()
        
        try:
            state_obj.use_nest = self._query_use_nest()
            
            actuation_msg = self._wait_for_message(
                'PANDION_RR_ACTUATION_SYS_STATUS',
                timeout=2.0
            )
            state_obj.actuation_mode = (
                actuation_msg.actuation_state if actuation_msg else -1
            )
            
            pandion_status = self._wait_for_message('PANDION_STATUS', timeout=2.0)
            if pandion_status:
                flight_regime = pandion_status.flight_regime
                state_obj.flight_regime = flight_regime
                state_obj.armed = (flight_regime >= 1 and flight_regime != 255)
            else:
                state_obj.armed = None
                state_obj.flight_regime = None
            
            monitor_msg = self._wait_for_message(
                'PANDION_MONITOR_CURRENT_STATUS',
                timeout=2.0
            )
            if monitor_msg:
                state_obj.set_monitors = self._extract_monitors_from_msg(
                    monitor_msg.currently_set
                )
                state_obj.overridden_monitors = self._extract_monitors_from_msg(
                    monitor_msg.currently_overridden
                )
            
            state_obj.captured = True
            return True, "State captured"
            
        except Exception:
            return False, "Failed to capture state"
    
    def _wait_for_message(self, msg_type, timeout=5.0):
        """
        Wait for a specific message type.
        
        Thread-safe wrapper around MAVLink recv_match.
        
        Args:
            msg_type: Message type to wait for
            timeout: Timeout in seconds
        
        Returns:
            Message object or None if timeout
        """
        with self.master_lock:
            return self.master.recv_match(type=msg_type, blocking=True, timeout=timeout)