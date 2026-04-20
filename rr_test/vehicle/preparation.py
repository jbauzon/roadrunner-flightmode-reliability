from __future__ import annotations

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
from typing import Any, List, Optional, Tuple, TYPE_CHECKING

from pymavlink import mavutil

if TYPE_CHECKING:
    from testing.callbacks import PreparationCallbacks

from .connection import UUTState
from .constants import (
    ActuationMode, FlightRegime, CommandResult, MsgType, USE_NEST_ENABLED,
    MONITOR_OVERRIDE_CANCEL, MONITOR_OVERRIDE_SUPPRESS,
    get_mode_name, get_flight_regime_name, get_command_result_name, is_armed,
    safe_int_field,
)
# Lazy import to avoid circular dependency (testing -> vehicle -> testing)
_build_actuator_feedback_dict = None


class UUTPreparation:
    """
    Handles UUT state capture, preparation, and restoration.
    
    Complete mode sequence: ARM → OPERATE → PLAYBACK → IBIT
    Then restoration after test complete.
    """
    
    def __init__(self, master: Any, config: Optional[dict] = None,
                 telemetry_logger: Optional[Any] = None,
                 callbacks: Optional[PreparationCallbacks] = None,
                 msg_queues: Optional[Any] = None,
                 error_log: Optional[Any] = None) -> None:
        """
        Initialize preparation manager.

        Args:
            master: MAVLink connection
            config: Configuration dictionary
            telemetry_logger: Optional logger for events
            callbacks: Optional PreparationCallbacks for UI communication
            msg_queues: Optional shared dispatch queues from _ExecutorMixin.
                        When provided, _wait_for_message reads from queues
                        instead of the socket directly (no lock needed).
            error_log: Optional ErrorLogger for persistent cross-session logging.
        """
        self.cb = callbacks or self._default_callbacks()
        self.master = master
        self.config = config or {}
        self.telemetry_logger = telemetry_logger
        self.error_log = error_log  # Optional — may be None
        self.initial_state = UUTState()
        self.use_nest_cache = None
        self.master_lock = threading.Lock()
        self._msg_queues = msg_queues
        # O-2: stop-check callback — executor wires this to self.running.
        # Preparation loops check this and abort early on Stop.
        self.should_stop: Any = lambda: False
    
    @staticmethod
    def _default_callbacks() -> PreparationCallbacks:
        """Lazy import to avoid circular dependency at module load time.

        We load ``testing/callbacks.py`` directly via importlib.util so that
        the ``testing`` package's ``__init__.py`` (which eagerly imports
        PyQt5-dependent modules) is never executed.
        """
        import importlib.util, pathlib, sys
        _name = 'testing.callbacks'
        if _name in sys.modules:
            return sys.modules[_name].PreparationCallbacks()
        _path = str(pathlib.Path(__file__).resolve().parent.parent / 'testing' / 'callbacks.py')
        spec = importlib.util.spec_from_file_location(_name, _path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[_name] = mod
        spec.loader.exec_module(mod)
        return mod.PreparationCallbacks()
    
    def capture_initial_state(self) -> Tuple[bool, str]:
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
        self.cb.on_log("Step: Capturing initial state...")
        
        if self.telemetry_logger:
            self.telemetry_logger.log_test_event(
                'STATE_CAPTURE',
                'Capturing initial vehicle state before test'
            )
        
        self.initial_state = UUTState()
        self.initial_state.timestamp = time.monotonic()
        
        try:
            # Query USE_NEST parameter
            self.cb.on_progress("Querying USE_NEST parameter...")
            use_nest = self._query_use_nest()

            if use_nest is None:
                self.cb.on_log(
                    "  \u26a0 USE_NEST query failed \u2014 will defensively disable USE_NEST on next iteration"
                )
                self.initial_state.use_nest = None  # Unknown, not 0
                self.initial_state.use_nest_query_failed = True
            else:
                self.initial_state.use_nest = use_nest
                self.initial_state.use_nest_query_failed = False
                self.cb.on_log(
                    f"  \u2713 USE_NEST = {use_nest} "
                    f"({'ENABLED' if use_nest == USE_NEST_ENABLED else 'DISABLED'})"
                )
            
            # Query actuation status
            self.cb.on_progress("Querying actuation status...")
            actuation_msg = self._wait_for_message(
                MsgType.ACTUATION_SYS_STATUS, 
                timeout=5.0
            )
            
            if not actuation_msg:
                raise Exception("Failed to receive actuation status")
            
            self.initial_state.actuation_mode = actuation_msg.actuation_state
            self.cb.on_log(
                f"  ✓ Actuation Mode = {actuation_msg.actuation_state}"
            )
            
            # Query armed state from PANDION_STATUS
            self.cb.on_progress("Querying armed state...")
            pandion_status = self._wait_for_message(MsgType.PANDION_STATUS, timeout=5.0)
            
            if not pandion_status:
                raise Exception("Failed to receive PANDION_STATUS")
            
            flight_regime = safe_int_field(pandion_status, 'flight_regime', FlightRegime.INVALID)
            self.initial_state.flight_regime = flight_regime
            self.initial_state.armed = is_armed(flight_regime)
            
            # Log with flight regime name
            regime_name = get_flight_regime_name(flight_regime)
            self.cb.on_log(f"  ✓ Flight Regime = {flight_regime} ({regime_name})")
            self.cb.on_log(f"  ✓ Armed = {self.initial_state.armed}")
            
            # Query monitor status
            self.cb.on_progress("Querying monitor status...")
            monitor_msg = self._wait_for_message(
                MsgType.MONITOR_STATUS,
                timeout=5.0
            )
            
            if not monitor_msg:
                self.cb.on_log(
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
                self.cb.on_log(
                    f"  ✓ SET Monitors: {len(self.initial_state.set_monitors)} monitor(s)"
                )
                self.cb.on_log(
                    f"  ✓ Overridden: {len(self.initial_state.overridden_monitors)} monitor(s)"
                )
            
            self.initial_state.captured = True
            
            self.cb.on_log("✓ Initial State Captured:")
            for line in self.initial_state.format_display().split('\n'):
                self.cb.on_log(f"  {line}")
            
            return True, "State captured successfully"
            
        except Exception as e:
            return False, f"State capture failed: {str(e)}"
    
    def prepare_for_playback(self) -> Tuple[bool, str]:
        """
        Prepare UUT for flight profile playback.

        Sequence:
          1. Set CLASSIC_MODE_EN = 1  (if not already)
          2. Set USE_NEST = 0         (if not already)
          3. ARM → OPERATE → PLAYBACK

        Note: CLASSIC_MODE_EN requires a vehicle reboot to take effect.
        The test software does not control vehicle input power — the
        operator must ensure the vehicle has been power-cycled at least
        once after CLASSIC_MODE_EN was first set.  On subsequent runs
        the parameter is already persisted in firmware flash.

        Returns:
            (success: bool, message: str)
        """
        self.cb.on_log("═══════════════════════════════════════════")
        self.cb.on_log("PLAYBACK PRE-FLIGHT PREPARATION")
        self.cb.on_log("═══════════════════════════════════════════")

        try:
            # Step 1: Set CLASSIC_MODE_EN = 1
            self.cb.on_log("→ Setting CLASSIC_MODE_EN = 1...")
            success, msg = self._set_param('CLASSIC_MODE_EN', 1)
            if not success:
                raise Exception(f"Could not set CLASSIC_MODE_EN: {msg}")
            self.cb.on_log(f"  ✓ {msg}")

            # Step 2: Ensure USE_NEST = 0
            if self.initial_state.use_nest != 0:
                self.cb.on_log("→ Setting USE_NEST = 0...")
                success, msg = self._set_use_nest(0)
                if not success:
                    self.cb.on_log(f"  ⚠ Could not disable USE_NEST: {msg}")
                else:
                    self.cb.on_log(f"  ✓ {msg}")
            else:
                self.cb.on_log("✓ USE_NEST already 0, skipping")

            # Step 3: ARM
            success, msg = self._arm_with_monitor_management()
            if not success:
                raise Exception(f"Failed to ARM: {msg}")
            self.cb.on_log(f"\n✓ {msg}")

            # Step 5: Wait for OPERATE
            self.cb.on_log("\n→ Waiting for OPERATE mode...")
            # Drain stale ACTUATION_SYS_STATUS so we only read post-ARM values
            if self._msg_queues is not None:
                self._msg_queues[MsgType.ACTUATION_SYS_STATUS].clear()
            operate_timeout = 10.0
            operate_start = time.monotonic()
            in_operate = False
            while time.monotonic() - operate_start < operate_timeout and not self.should_stop():
                mode_msg = self._wait_for_message(
                    MsgType.ACTUATION_SYS_STATUS, timeout=1.0
                )
                if mode_msg and mode_msg.actuation_state == ActuationMode.OPERATE:
                    self.cb.on_log("  ✓ Vehicle in OPERATE mode")
                    in_operate = True
                    break
                time.sleep(0.2)

            if not in_operate:
                raise Exception(
                    f"Vehicle did not enter OPERATE mode within {operate_timeout}s"
                )

            # Step 6: Clear monitors until none remain (condition-based, not time-based)
            self.cb.on_log("\n→ Clearing monitors before PLAYBACK...")
            self._clear_monitors_until_clean(timeout=20.0)

            # Step 7: Enter PLAYBACK
            self.cb.on_log("\n→ Requesting PLAYBACK mode...")
            with self.master_lock:
                self.master.mav.pandion_rr_actuation_request_mode_send(
                    requested_mode=int(ActuationMode.PLAYBACK)
                )

            playback_timeout = 10.0
            playback_start = time.monotonic()
            while time.monotonic() - playback_start < playback_timeout and not self.should_stop():
                mode_msg = self._wait_for_message(
                    MsgType.ACTUATION_SYS_STATUS, timeout=0.5
                )
                if mode_msg and mode_msg.actuation_state == ActuationMode.PLAYBACK:
                    self.cb.on_log("  ✓ Vehicle in PLAYBACK mode")
                    break
                time.sleep(0.1)
            else:
                raise Exception("Failed to enter PLAYBACK mode")

            # Clear any monitors that appeared during PLAYBACK entry
            self._clear_monitors_until_clean(timeout=10.0)

            self.cb.on_log("\n✓ Playback preparation complete — ready to stream profile")
            return True, "Playback preparation complete"

        except Exception as e:
            self.cb.on_log(f"\n✗ Playback preparation FAILED: {e}")
            return False, str(e)

    def _set_param(self, param_name: str, value: Any) -> Tuple[bool, str]:
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

            # Flush any stale param responses before sending PARAM_SET so that
            # a leftover response for a different parameter cannot falsely pass
            # or fail verification of this one.
            if self._msg_queues is not None:
                for qt in ('PANDION_RR_PARAM_VALUE', MsgType.PARAM_VALUE):
                    try:
                        self._msg_queues[qt].clear()
                    except Exception:
                        pass

            with self.master_lock:
                self.master.mav.param_set_send(
                    self.master.target_system,
                    self.master.target_component,
                    param_bytes,
                    float(value),
                    mavutil.mavlink.MAV_PARAM_TYPE_UINT8
                )

            time.sleep(1.0)

            # Request read-back for verification
            with self.master_lock:
                self.master.mav.param_request_read_send(
                    self.master.target_system,
                    self.master.target_component,
                    param_bytes,
                    -1
                )

            timeout = 5.0
            start = time.monotonic()
            while time.monotonic() - start < timeout and not self.should_stop():
                # Pandion firmware responds with PANDION_RR_PARAM_VALUE,
                # not standard PARAM_VALUE.  Try custom message first,
                # then fall back to standard for SITL compatibility.
                # Use a 1.0s poll timeout to avoid a tight loop that can
                # race past a slow firmware response.
                msg = self._wait_for_message('PANDION_RR_PARAM_VALUE', timeout=1.0)
                if msg is None:
                    msg = self._wait_for_message(MsgType.PARAM_VALUE, timeout=0.5)
                if msg:
                    name = (
                        msg.param_id.decode('utf-8').rstrip('\x00')
                        if isinstance(msg.param_id, bytes)
                        else str(msg.param_id).rstrip('\x00')
                    )
                    # Only accept a response whose param_id matches what we set.
                    # A stale response for a different parameter must be ignored.
                    if name == param_name:
                        actual = int(msg.param_value)
                        if actual == int(value):
                            return True, f"{param_name} = {actual}"
                        else:
                            return False, (
                                f"{param_name} verification failed "
                                f"(expected {value}, got {actual})"
                            )

            return False, f"{param_name} set sent but no verification response"

        except Exception as e:
            return False, f"Error setting {param_name}: {str(e)}"

    def prepare_for_test(self) -> Tuple[bool, str]:
        """
        Prepare UUT for testing.
        
        Full sequence: ARM -> OPERATE -> clear monitors -> PLAYBACK -> IBIT
        
        Why PLAYBACK? Vehicle firmware requires OPERATE -> PLAYBACK -> IBIT.
        Direct OPERATE -> IBIT is not permitted.
        
        Returns:
            (success: bool, message: str)
        """
        self.cb.on_log("═══════════════════════════════════════════")
        self.cb.on_log("PRE-FLIGHT PREPARATION")
        self.cb.on_log("═══════════════════════════════════════════")
        
        try:
            # Step 1: Disable USE_NEST if needed
            self._disable_use_nest_if_needed()

            # Step 2: ARM vehicle if needed
            self._arm_vehicle_if_needed()

            # Step 3: Wait for automatic transition to OPERATE mode
            self._wait_for_operate(timeout=15.0)

            # Step 4: Continuously clear monitors before PLAYBACK
            self._clear_monitors_timed(
                duration=5.0,
                label='before PLAYBACK',
                event_type='MONITOR_CONTINUOUS_CLEAR',
            )

            # Step 5: Enter PLAYBACK mode
            self._enter_mode(
                target=ActuationMode.PLAYBACK,
                timeout=10.0,
                event_request='PLAYBACK_REQUEST',
                event_entered='PLAYBACK_ENTERED',
                event_failed='PLAYBACK_FAILED',
                log_interval=2,
            )

            # Step 6: Clear monitors in PLAYBACK
            self._clear_monitors_timed(
                duration=3.0,
                label='in PLAYBACK before IBIT',
                event_type='MONITOR_PLAYBACK_CLEAR',
            )

            # Step 7: Enter IBIT mode
            self._enter_mode(
                target=ActuationMode.IBIT,
                timeout=30.0,
                event_request='IBIT_REQUEST',
                event_entered='IBIT_ENTERED',
                event_failed='IBIT_FAILED',
                log_interval=5,
            )
            
            self.cb.on_log("\n✓ Pre-flight preparation complete")
            self.cb.on_log(
                "  Sequence: ARM → OPERATE → Clear Monitors → "
                "PLAYBACK → Clear Monitors → IBIT ✓"
            )
            
            return True, "Preparation complete"
            
        except Exception as e:
            self.cb.on_log(f"\n✗ Pre-flight preparation FAILED: {e}")
            return False, str(e)

    # ── prepare_for_test sub-steps ──────────────────────────────────────

    def _disable_use_nest_if_needed(self) -> None:
        """Step 1: Disable USE_NEST if it is currently enabled or unknown."""
        if getattr(self.initial_state, 'use_nest_query_failed', False):
            # Query failed — defensively set to 0 to be safe
            self.cb.on_log(
                "\u2192 USE_NEST state unknown (query failed) \u2014 defensively setting to 0"
            )
            success, msg = self._set_use_nest(0)
            if success:
                self.cb.on_log(f"  \u2713 {msg}")
            else:
                self.cb.on_log(f"  \u26a0 Could not set USE_NEST: {msg}")
            return

        if self.initial_state.use_nest is not None:
            if self.initial_state.use_nest != 0:
                self.cb.on_progress("Disabling USE_NEST...")
                self.cb.on_log("→ Setting USE_NEST = 0 (DISABLE)")
                if self.telemetry_logger:
                    self.telemetry_logger.log_test_event(
                        'USE_NEST_DISABLE',
                        'Setting USE_NEST parameter to 0 (DISABLED)'
                    )
                success, msg = self._set_use_nest(0)
                if not success:
                    self.cb.on_log(f"  ⚠ Could not disable USE_NEST: {msg}")
                else:
                    self.cb.on_log(f"  ✓ {msg}")
            else:
                self.cb.on_log("✓ USE_NEST already disabled, skipping")
        else:
            self.cb.on_log("✓ USE_NEST not available on this vehicle, skipping")

    def _arm_vehicle_if_needed(self) -> None:
        """Step 2: ARM the vehicle with iterative monitor management."""
        if not self.initial_state.armed:
            success, msg = self._arm_with_monitor_management()
            if not success:
                skip_arm = self.config.get('skip_arm_for_ibit', False)
                if skip_arm:
                    self.cb.on_log(
                        f"\n⚠ ARM failed but 'skip_arm_for_ibit' enabled"
                    )
                    self.cb.on_log(
                        f"  → Proceeding to IBIT without ARM (may fail)"
                    )
                else:
                    raise Exception(f"Failed to ARM: {msg}")
            else:
                self.cb.on_log(f"\n✓ {msg}")
        else:
            self.cb.on_log("✓ Vehicle already armed, skipping")

    def _wait_for_operate(self, timeout: float = 15.0) -> None:
        """Step 3: Wait for OPERATE mode after ARM. POS_CHECK is accepted as an
        intermediate state (TAU Mk2 elevon vehicles: OFF → POS_CHECK → OPERATE)."""
        self.cb.on_log("\n→ Waiting for vehicle to enter OPERATE mode...")
        self.cb.on_progress("Waiting for OPERATE mode...")
        if self.telemetry_logger:
            self.telemetry_logger.log_test_event(
                'MODE_TRANSITION_WAIT',
                'Waiting for automatic transition to OPERATE mode'
            )
        start = time.monotonic()
        while time.monotonic() - start < timeout and not self.should_stop():
            mode_msg = self._wait_for_message(
                MsgType.ACTUATION_SYS_STATUS, timeout=1.0
            )
            if mode_msg:
                current_mode = mode_msg.actuation_state
                if current_mode == ActuationMode.OPERATE:
                    self.cb.on_log("  ✓ Vehicle entered OPERATE mode")
                    if self.telemetry_logger:
                        self.telemetry_logger.log_test_event(
                            'MODE_CHANGE',
                            'Vehicle automatically transitioned to OPERATE mode'
                        )
                    return
                elif current_mode == ActuationMode.POSITION_CHECK:
                    # TAU Mk2 elevon vehicles perform position check before OPERATE
                    self.cb.on_log("  → POS_CHECK in progress (TAU Mk2 elevons)...")
                    self.cb.on_progress("Position check in progress (TAU Mk2)...")
                    # Don't break — keep waiting for OPERATE
                elif current_mode == ActuationMode.TERMINAL:
                    self.cb.on_log(
                        "  ✗ POS_CHECK FAILED — vehicle in TERMINAL mode"
                    )
                    self.cb.on_alert(
                        "POS_CHECK FAILED — vehicle in TERMINAL mode. "
                        "Power cycle required."
                    )
                    raise Exception(
                        "POS_CHECK resulted in TERMINAL mode. Power cycle required."
                    )
                else:
                    self.cb.on_log(
                        f"  Current mode: {current_mode} "
                        f"({get_mode_name(current_mode)})"
                    )
            time.sleep(0.5)
        # Timeout expired without OPERATE — log warning, don't abort (PLAYBACK will catch it)
        self.cb.on_log(
            f"  ⚠ Vehicle did not enter OPERATE mode within {timeout}s"
        )
        # Don't alert here — this is expected for TAU elevons (POS_CHECK takes time)
        # Log to CSV and JSONL for traceability
        if self.telemetry_logger:
            self.telemetry_logger.log_test_event(
                'OPERATE_WAIT_TIMEOUT',
                f'Vehicle did not enter OPERATE within {timeout}s — proceeding'
            )
        if self.error_log:
            self.error_log.info(
                'ARM',
                getattr(self, '_serial', 'unknown'),
                getattr(self, '_iteration', lambda: 0)(),
                f'OPERATE mode not confirmed within {timeout}s after ARM — proceeding',
            )
        self.cb.on_log(f"  → Proceeding to clear monitors anyway...")

    def _clear_monitors_timed(self, duration: float, label: str, event_type: str) -> None:
        """Clear SET monitors for a fixed duration, logging progress."""
        self.cb.on_log(
            f"\n→ Continuously clearing monitors {label}..."
        )
        self.cb.on_progress("Clearing monitors...")
        if self.telemetry_logger:
            self.telemetry_logger.log_test_event(
                event_type, f'Starting continuous monitor clearing {label}'
            )
        start = time.monotonic()
        clear_count = 0
        while time.monotonic() - start < duration and not self.should_stop():
            current_set = self._get_current_set_monitors()
            if current_set:
                clear_count += 1
                self.cb.on_log(
                    f"  [{clear_count}] Clearing {len(current_set)} "
                    f"SET monitors: {current_set}"
                )
                all_cleared, remaining = self._clear_specific_monitors(current_set)
                if not all_cleared:
                    self.cb.on_log(
                        f"    ⚠ {len(remaining)} monitors couldn't be cleared"
                    )
            else:
                self.cb.on_log(f"  ✓ No SET monitors detected")
            time.sleep(0.5)
        self.cb.on_log(
            f"  ✓ Monitor clearing complete ({clear_count} clear operations)"
        )
        # Final check
        final_set = self._get_current_set_monitors()
        if final_set:
            self.cb.on_log(
                f"  ⚠ Warning: {len(final_set)} monitors still SET: {final_set}"
            )
            if self.telemetry_logger:
                self.telemetry_logger.log_test_event(
                    'MONITOR_WARNING',
                    f'{len(final_set)} monitors still SET {label}: {final_set}'
                )
            if self.error_log:
                self.error_log.warning(
                    'MONITOR',
                    getattr(self, '_serial', 'unknown'),
                    getattr(self, '_iteration', lambda: 0)(),
                    f'{len(final_set)} monitors still SET after clearing {label}: {final_set}',
                    {'monitors': list(final_set), 'label': label},
                )
        else:
            self.cb.on_log(f"  ✓ All monitors clear")

    def _enter_mode(self, target: int, timeout: float, event_request: str, event_entered: str,
                    event_failed: str, log_interval: int = 2) -> None:
        """
        Request a mode transition and wait for confirmation.

        Args:
            target: ActuationMode to enter
            timeout: Max seconds to wait
            event_request / event_entered / event_failed: telemetry event names
            log_interval: How often (seconds) to log "still waiting"
        """
        target_name = get_mode_name(target)
        self.cb.on_log(
            f"\n→ Requesting transition → {target_name}..."
        )
        self.cb.on_progress(f"Entering {target_name} mode...")
        if self.telemetry_logger:
            self.telemetry_logger.log_test_event(
                event_request,
                f'Requesting transition to {target_name} mode'
            )
        self.cb.on_log(
            f"  Sending {target_name} mode request (mode {int(target)})..."
        )
        # Flush stale actuation status messages from before the mode request.
        # The queue may contain many OPERATE messages from the monitor clearing
        # phase — we don't want to mistake them for the post-transition state.
        if self._msg_queues is not None:
            self._msg_queues[MsgType.ACTUATION_SYS_STATUS].clear()
        with self.master_lock:
            self.master.mav.pandion_rr_actuation_request_mode_send(
                requested_mode=int(target)
            )
        self.cb.on_log(
            f"  Monitoring mode for up to {timeout:.0f} seconds..."
        )
        start = time.monotonic()
        last_log_second = -1
        while time.monotonic() - start < timeout and not self.should_stop():
            mode_msg = self._wait_for_message(
                MsgType.ACTUATION_SYS_STATUS, timeout=0.5
            )
            if mode_msg:
                current_mode = mode_msg.actuation_state
                if current_mode == target:
                    elapsed = time.monotonic() - start
                    self.cb.on_log(
                        f"  \u2713 Vehicle entered {target_name} mode "
                        f"after {elapsed:.1f} seconds"
                    )
                    if self.telemetry_logger:
                        self.telemetry_logger.log_test_event(
                            event_entered,
                            f'Vehicle entered {target_name} mode '
                            f'after {elapsed:.1f} seconds'
                        )
                    return
                else:
                    elapsed = time.monotonic() - start
                    current_second = int(elapsed)
                    if current_second % log_interval == 0 and current_second != last_log_second and elapsed > 0:
                        last_log_second = current_second
                        self.cb.on_log(
                            f"    [{elapsed:.0f}s] Current mode: "
                            f"{get_mode_name(current_mode)}, "
                            f"waiting for {target_name}..."
                        )
            time.sleep(0.1)

        # Failed
        final_msg = self._wait_for_message(
            MsgType.ACTUATION_SYS_STATUS, timeout=2.0
        )
        final_mode = final_msg.actuation_state if final_msg else -1
        final_str = get_mode_name(final_mode)
        if self.telemetry_logger:
            self.telemetry_logger.log_test_event(
                event_failed,
                f'Failed to enter {target_name} mode - stuck in {final_str}'
            )
        raise Exception(
            f"Failed to enter {target_name} mode after {timeout:.0f} seconds.\n"
            f"  Current mode: {final_mode} ({final_str})\n"
            f"  Expected: {int(target)} ({target_name})\n"
            f"  The vehicle may have conditions preventing {target_name} mode entry."
        )
    
    def restore_original_state(self) -> Tuple[bool, str]:
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
        self.cb.on_log("═══════════════════════════════════════════")
        self.cb.on_log("POST-FLIGHT RESTORATION")
        self.cb.on_log("═══════════════════════════════════════════")
        
        if self.telemetry_logger:
            self.telemetry_logger.log_test_event(
                'RESTORATION_START',
                'Starting restoration to original vehicle state'
            )
        
        if not self.initial_state.captured:
            self.cb.on_log("⚠ No initial state captured, cannot restore.")
            return False, "No initial state"
        
        self.cb.on_log("Target State (from initial capture):")
        for line in self.initial_state.format_display().split('\n'):
            self.cb.on_log(f"  {line}")
        
        try:
            self._ensure_operate_mode()
            self._clear_overrides_before_disarm()
            self._disarm_if_needed()
            self._transition_to_off()
            
            return True, "Restoration complete"
            
        except Exception as e:
            self.cb.on_log(f"✗ Restoration error: {e}")
            return False, str(e)

    # ── restore_original_state sub-steps ────────────────────────────────

    def _ensure_operate_mode(self):
        """If vehicle is in IBIT, transition to OPERATE before restoration."""
        current_mode_msg = self._wait_for_message(
            MsgType.ACTUATION_SYS_STATUS,
            timeout=3.0
        )
        current_mode = current_mode_msg.actuation_state if current_mode_msg else -1
        
        if current_mode == ActuationMode.TERMINAL:
            self.cb.on_log(
                "\u2717 Vehicle is in TERMINAL mode \u2014 requires power cycle to recover"
            )
            self.cb.on_alert(
                "TERMINAL MODE DETECTED \u2014 Power cycle vehicle before retesting. "
                "Disable relay, wait 10s, re-enable relay."
            )
            if self.telemetry_logger:
                self.telemetry_logger.log_test_event(
                    'TERMINAL_MODE',
                    'Vehicle in TERMINAL mode \u2014 power cycle required'
                )
            if self.error_log:
                self.error_log.critical(
                    'STATE',
                    getattr(self, '_serial', 'unknown'),
                    0,
                    'Vehicle in TERMINAL mode \u2014 power cycle required before retesting',
                )
            raise Exception(
                "Vehicle in TERMINAL mode. Power cycle required. "
                "Disable relay for 10+ seconds then re-enable."
            )

        if current_mode == ActuationMode.IBIT:  # Still in IBIT
            self.cb.on_log(
                f"⚠ Still in IBIT mode, requesting OPERATE first..."
            )
            with self.master_lock:
                self.master.mav.pandion_rr_actuation_request_mode_send(
                    requested_mode=ActuationMode.OPERATE
                )
            time.sleep(3.0)
            
            verify_msg = self._wait_for_message(
                MsgType.ACTUATION_SYS_STATUS,
                timeout=3.0
            )
            if verify_msg and verify_msg.actuation_state == ActuationMode.OPERATE:
                self.cb.on_log(f"  ✓ Vehicle in OPERATE mode")
            else:
                self.cb.on_log(f"  ⚠ Could not transition to OPERATE")
        
        elif current_mode == ActuationMode.OPERATE:
            self.cb.on_log(f"✓ Vehicle already in OPERATE mode")
        else:
            self.cb.on_log(f"⚠ Unexpected mode: {current_mode}")
        
        time.sleep(1.0)

    def _clear_overrides_before_disarm(self):
        """Clear any monitor overrides set during test before disarming."""
        self.cb.on_log("\n→ Clearing overridden monitors BEFORE disarm...")
        current_overridden = self._get_current_overridden_monitors()
        
        if current_overridden:
            self.cb.on_log(
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
                    self.master.mav.pandion_monitor_override_cmd_send(MONITOR_OVERRIDE_CANCEL, mid)
                    time.sleep(0.01)
            
            time.sleep(2.0)
            
            verify_overridden = self._get_current_overridden_monitors()
            if verify_overridden:
                self.cb.on_log(
                    f"  ⚠ {len(verify_overridden)} monitors still overridden: "
                    f"{verify_overridden}"
                )
            else:
                self.cb.on_log(f"  ✓ All monitors cleared before disarm")
        else:
            self.cb.on_log(f"  ✓ No overridden monitors to clear")

    def _disarm_if_needed(self):
        """Disarm the vehicle if it wasn't originally armed."""
        if not self.initial_state.armed:
            pandion_status = self._wait_for_message(MsgType.PANDION_STATUS, timeout=3.0)
            
            if pandion_status:
                flight_regime = pandion_status.flight_regime
                is_vehicle_armed = is_armed(flight_regime)
                
                if is_vehicle_armed:
                    self.cb.on_log(
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
                        self.cb.on_log(f"  ✓ {message}")
                    else:
                        self.cb.on_log(f"  ⚠ DISARM failed: {message}")
                        self.cb.on_alert(
                            f"⚠ DISARM FAILED — vehicle may remain ARMED. "
                            f"Manual inspection required before next test."
                        )
                        self.cb.on_log(
                            f"  ⚠ Proceeding to OFF mode — verify vehicle is physically safe"
                        )
                        if self.error_log:
                            self.error_log.warning(
                                'STATE',
                                getattr(self, '_serial', 'unknown'),
                                0,
                                f"DISARM FAILED after 5 attempts — vehicle may remain ARMED",
                                {'message': message},
                            )
                        if self.telemetry_logger:
                            self.telemetry_logger.log_test_event(
                                'DISARM_FAILED',
                                message
                            )
                else:
                    self.cb.on_log(f"✓ Vehicle already disarmed")
        
        time.sleep(2.0)

    def _transition_to_off(self):
        """Request transition to OFF mode and verify."""
        self.cb.on_log("\n→ Requesting transition to OFF mode...")
        with self.master_lock:
            self.master.mav.pandion_rr_actuation_request_mode_send(requested_mode=int(ActuationMode.OFF))
        
        time.sleep(3.0)
        
        final_mode_msg = self._wait_for_message(
            MsgType.ACTUATION_SYS_STATUS,
            timeout=3.0
        )
        
        if final_mode_msg:
            final_mode = final_mode_msg.actuation_state
            mode_str = get_mode_name(final_mode)
            
            if final_mode == ActuationMode.OFF:
                self.cb.on_log(
                    f"✓ Final actuation mode: {final_mode} ({mode_str}) ✓"
                )
            else:
                self.cb.on_log(
                    f"⚠ Final actuation mode: {final_mode} ({mode_str}) - "
                    f"expected OFF"
                )
            
            if self.telemetry_logger:
                self.telemetry_logger.log_test_event(
                    'MODE_CHECK',
                    f'Final mode after restoration: {mode_str}'
                )
        else:
            self.cb.on_log(f"⚠ Could not verify final mode")
    
    def verify_final_state(self, relay_was_disabled: bool = False) -> None:
        """
        Capture and verify final state matches initial.
        
        Args:
            relay_was_disabled: If True, skip verification (vehicle powered off)
        """
        self.cb.on_log("═══════════════════════════════════════════")
        self.cb.on_log("FINAL STATE VERIFICATION")
        self.cb.on_log("═══════════════════════════════════════════")
        
        # Skip verification if relay was disabled (vehicle is powered off)
        if relay_was_disabled:
            self.cb.on_log("⚠ Relay was disabled - skipping state verification")
            self.cb.on_log("  Reason: Cannot query vehicle state without power")
            self.cb.on_log("  Result: Vehicle is in safe powered-off state ✓")
            
            if self.telemetry_logger:
                self.telemetry_logger.log_test_event(
                    'STATE_VERIFICATION_SKIPPED',
                    'Relay disabled - vehicle powered off, cannot query final state'
                )
            return
        
        final_state = UUTState()
        success, _ = self._capture_current_state(final_state)
        
        if not success:
            self.cb.on_log("✗ Failed to capture final state for verification.")
            return
        
        self.cb.on_log("Final State After Restoration:")
        for line in final_state.format_display().split('\n'):
            self.cb.on_log(f"  {line}")
        
        if self.initial_state.matches(final_state):
            self.cb.on_log("✓✓✓ STATE SUCCESSFULLY RESTORED TO ORIGINAL ✓✓✓")
            
            if self.telemetry_logger:
                self.telemetry_logger.log_test_event(
                    'STATE_VERIFIED',
                    'Final state matches initial state - restoration successful'
                )
        else:
            differences = self.initial_state.get_differences(final_state)
            self.cb.on_log("⚠⚠⚠ STATE RESTORATION MISMATCH ⚠⚠⚠")
            
            for diff in differences:
                self.cb.on_log(f"  ⚠ {diff}")
            
            if self.telemetry_logger:
                self.telemetry_logger.log_test_event(
                    'STATE_MISMATCH',
                    f'State restoration mismatch detected: {"; ".join(differences)}'
                )
    
    # ========== HELPER METHODS ==========
    
    def _arm_with_monitor_management(self) -> Tuple[bool, str]:
        """
        ARM vehicle: check monitors → clear → try ARM → repeat until success.
        
        Returns:
            (success: bool, message: str)
        """
        self.cb.on_progress("Arming vehicle with monitor management...")
        self.cb.on_log(
            "→ Attempting to ARM vehicle with iterative monitor management..."
        )
        
        if self.telemetry_logger:
            self.telemetry_logger.log_test_event(
                'ARM_REQUEST',
                'Starting ARM sequence with monitor management'
            )
        
        arm_timeout = self.config.get('arm_timeout', 60.0)
        max_iterations = self.config.get('max_arm_iterations', 20)
        
        start_time = time.monotonic()
        iteration = 0
        
        while iteration < max_iterations and (time.monotonic() - start_time) < arm_timeout and not self.should_stop():
            iteration += 1
            self.cb.on_log(f"\n  Iteration {iteration}/{max_iterations}:")
            
            # Check monitors
            self.cb.on_log(f"    Checking monitor status...")
            current_set = self._get_current_set_monitors()
            
            if len(current_set) > 0:
                self.cb.on_log(
                    f"    Found {len(current_set)} SET monitors: {current_set}"
                )
                all_cleared, remaining = self._clear_specific_monitors(current_set)
                
                if not all_cleared:
                    self.cb.on_log(
                        f"    ⚠ Some monitors couldn't be cleared (may be hardware faults)"
                    )
            else:
                self.cb.on_log(f"    ✓ No SET monitors")
            
            # Try ARM
            self.cb.on_log(f"    Attempting ARM command...")
            arm_success, arm_message = self._try_arm_once()
            
            if arm_success:
                self.cb.on_log(f"    ✓ Vehicle ARMED successfully!")
                self.cb.on_log(f"  Success on iteration {iteration}")
                
                if self.telemetry_logger:
                    self.telemetry_logger.log_test_event(
                        'ARM_SUCCESS',
                        f'Vehicle ARMED successfully after {iteration} iteration(s)'
                    )
                
                return True, f"Vehicle ARMED (iterations: {iteration})"
            else:
                self.cb.on_log(f"    ✗ ARM failed: {arm_message}")
            
            time.sleep(0.5)
            
            # Check what happened
            post_arm_set = self._get_current_set_monitors()
            if post_arm_set:
                self.cb.on_log(
                    f"    → After ARM failure, {len(post_arm_set)} monitors are SET"
                )
            else:
                self.cb.on_log(
                    f"    → No new monitors SET, but ARM still failed"
                )
            
            time.sleep(0.3)
        
        # ARM failed
        self.cb.on_log(f"\n✗ ARM FAILED after {iteration} iterations")
        final_set = self._get_current_set_monitors()
        
        if self.telemetry_logger:
            self.telemetry_logger.log_test_event(
                'ARM_FAILED',
                f'ARM failed after {iteration} iterations - '
                f'{len(final_set)} monitors cannot be cleared'
            )
        
        if final_set:
            self.cb.on_log(
                f"  Final status: {len(final_set)} monitors still SET: {final_set}"
            )
            self.cb.on_log(
                f"  These monitors could not be cleared - likely hardware faults"
            )
            if 52 in final_set:
                self.cb.on_alert(
                    "THERMAL SHUTDOWN MONITOR SET — servo over-temperature. "
                    "Allow vehicle to cool before next test attempt."
                )
                if self.error_log:
                    self.error_log.critical(
                        'IBIT',
                        getattr(self, '_serial', 'unknown'),
                        getattr(self, '_iteration', lambda: 0)(),
                        'ARM blocked by thermal shutdown monitor (monitor 52)',
                        {'monitors_set': list(final_set)},
                    )
                return False, (
                    f"ARM blocked by THERMAL SHUTDOWN monitor — vehicle over-temperature. "
                    f"Allow to cool. Other monitors SET: {final_set - {52}}"
                )
            return False, (
                f"ARM failed - {len(final_set)} monitors cannot be cleared "
                f"(hardware faults)"
            )
        else:
            self.cb.on_log(f"  Final status: No monitors SET, but ARM still failed")
            return False, "ARM failed - no monitors SET but vehicle refuses to ARM"
    
    def _try_arm_once(self) -> Tuple[bool, str]:
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
        ack = self._wait_for_message(MsgType.COMMAND_ACK, timeout=2.0)
        
        if ack and ack.command == mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM:
            result_str = get_command_result_name(ack.result)
            
            if ack.result == CommandResult.ACCEPTED:
                # Drain stale pre-ARM PANDION_STATUS messages so the next
                # status we read reflects the post-ARM state, not a queued
                # pre-ARM one.  Fixes false "ACK received but not armed"
                # when the dispatch queue has backlog (e.g. after a power
                # cycle wait in the Playback preparation flow).
                if self._msg_queues is not None:
                    self._msg_queues[MsgType.PANDION_STATUS].clear()

                time.sleep(0.3)
                
                # Verify with PANDION_STATUS
                pandion_status = self._wait_for_message(MsgType.PANDION_STATUS, timeout=2.0)
                if pandion_status:
                    flight_regime = pandion_status.flight_regime
                    if is_armed(flight_regime):
                        return True, "ARMED"
                    else:
                        return False, (
                            f"ACK received but not armed (flight regime: {flight_regime})"
                        )
            else:
                return False, result_str
        else:
            return False, "No ACK received"
    
    def _disarm_with_improved_retry(self, max_attempts: int = 5) -> Tuple[bool, str]:
        """
        Improved disarm with better ACK handling and longer timeouts.
        
        Args:
            max_attempts: Maximum number of DISARM attempts
        
        Returns:
            (success: bool, message: str)
        """
        for attempt in range(1, max_attempts + 1):
            self.cb.on_log(f"  DISARM attempt {attempt}/{max_attempts}...")
            
            with self.master_lock:
                self.master.mav.command_long_send(
                    self.master.target_system, 1,
                    mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
                    0, 0, 0, 0, 0, 0, 0, 0
                )
            
            # Wait for ACK with longer timeout
            timeout = 5.0
            start_time = time.monotonic()
            ack_received = False
            
            while time.monotonic() - start_time < timeout and not self.should_stop():
                ack = self._wait_for_message(MsgType.COMMAND_ACK, timeout=0.5)
                
                if ack and ack.command == mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM:
                    ack_received = True
                    
                    if ack.result == CommandResult.ACCEPTED:
                        self.cb.on_log(f"    ✓ DISARM command accepted")
                        
                        # Wait for actual disarm (vehicle takes time)
                        time.sleep(2.0)
                        
                        # Verify with multiple checks
                        for verify_attempt in range(5):
                            ps = self._wait_for_message(MsgType.PANDION_STATUS, timeout=1.0)
                            if ps:
                                if ps.flight_regime == FlightRegime.GROUND_DISARMED:
                                    self.cb.on_log(
                                        f"    ✓ DISARMED verified (flight regime 0)"
                                    )
                                    
                                    if self.telemetry_logger:
                                        self.telemetry_logger.log_test_event(
                                            'DISARM_SUCCESS',
                                            f'Vehicle DISARMED on attempt {attempt}'
                                        )
                                    
                                    return True, f"DISARMED on attempt {attempt}"
                                else:
                                    self.cb.on_log(
                                        f"    ⚠ Still armed (flight regime: "
                                        f"{ps.flight_regime}), waiting..."
                                    )
                                    time.sleep(0.5)
                            else:
                                self.cb.on_log(
                                    f"    ⚠ No PANDION_STATUS received"
                                )
                                time.sleep(0.5)
                        
                        self.cb.on_log(
                            f"    ✗ DISARM accepted but verification failed"
                        )
                    else:
                        result_str = get_command_result_name(ack.result)
                        self.cb.on_log(f"    ✗ DISARM rejected: {result_str}")
                    
                    break
                
                time.sleep(0.1)
            
            if not ack_received:
                self.cb.on_log(f"    ✗ No ACK received within {timeout}s")
            
            # Wait before retry
            if attempt < max_attempts:
                wait_time = min(attempt * 2, 5)
                self.cb.on_log(f"    → Retrying in {wait_time}s...")
                time.sleep(wait_time)
        
        return False, f"DISARM failed after {max_attempts} attempts"
    
    def _clear_specific_monitors(self, monitor_ids: List[int]) -> Tuple[bool, List[int]]:
        """
        Clear only the specific monitors that are SET.
        
        Args:
            monitor_ids: List of monitor IDs to clear
        
        Returns:
            (all_cleared: bool, still_set: list)
        """
        if not monitor_ids:
            return True, []
        
        self.cb.on_log(
            f"    Clearing {len(monitor_ids)} monitors: {monitor_ids}"
        )
        
        if self.telemetry_logger:
            self.telemetry_logger.log_test_event(
                'MONITOR_CLEAR',
                f'Clearing {len(monitor_ids)} safety monitors: {monitor_ids}'
            )
        
        with self.master_lock:
            for monitor_id in monitor_ids:
                self.master.mav.pandion_monitor_override_cmd_send(MONITOR_OVERRIDE_SUPPRESS, monitor_id)
                time.sleep(0.01)
        
        time.sleep(1.5)
        
        # Verify
        verify_msg = self._wait_for_message(
            MsgType.MONITOR_STATUS,
            timeout=2.0
        )
        
        if not verify_msg:
            return False, monitor_ids
        
        still_set = self._extract_monitors_from_msg(verify_msg.currently_set)
        cleared = set(monitor_ids) - set(still_set)
        
        if cleared:
            self.cb.on_log(
                f"    ✓ Cleared {len(cleared)} monitors: {sorted(list(cleared))}"
            )
        
        if still_set:
            self.cb.on_log(
                f"    ✗ {len(still_set)} monitors remain SET: {still_set}"
            )
        else:
            self.cb.on_log(f"    ✓ All monitors cleared")
        
        return len(still_set) == 0, still_set
    
    def _get_current_set_monitors(self) -> List[int]:
        """Get list of currently SET monitors.

        S-9: If no message received, log a one-time warning and return empty
        list. Returning empty (rather than blocking) is safer — it means we
        proceed without clearing monitors rather than stalling the preparation
        sequence. Firmware that does not support this message is treated as
        having no monitors to clear.
        """
        monitor_msg = self._wait_for_message(
            MsgType.MONITOR_STATUS,
            timeout=2.0
        )

        if not monitor_msg:
            # Increment miss counter (first miss only logs a warning)
            self._monitor_query_misses = getattr(self, '_monitor_query_misses', 0) + 1
            if self._monitor_query_misses == 1:
                self.cb.on_log(
                    "  \u26a0 PANDION_MONITOR_CURRENT_STATUS not received \u2014 "
                    "monitor state unknown (firmware may not support this message)"
                )
            return []

        return self._extract_monitors_from_msg(monitor_msg.currently_set)
    
    def _get_current_overridden_monitors(self) -> List[int]:
        """Get list of currently overridden monitors"""
        monitor_msg = self._wait_for_message(
            MsgType.MONITOR_STATUS,
            timeout=3.0
        )
        
        return self._extract_monitors_from_msg(
            monitor_msg.currently_overridden
        ) if monitor_msg else []
    
    def _extract_monitors_from_msg(self, byte_array: Any) -> List[int]:
        """Extract monitor IDs from byte array"""
        monitors = []
        for byte_idx, byte_val in enumerate(byte_array):
            for bit in range(8):
                if byte_val & (1 << bit):
                    monitors.append(byte_idx * 8 + bit)
        return monitors
    
    def _query_use_nest(self) -> Optional[int]:
        """Query USE_NEST parameter with caching"""
        if self.use_nest_cache is not None:
            return self.use_nest_cache

        try:
            # Drain any stale PARAM_VALUE / PANDION_RR_PARAM_VALUE messages
            # so the response to our request is not confused with old ones.
            if self._msg_queues is not None:
                # Drain from dispatch queues — never touch the socket directly
                for qt in ('PANDION_RR_PARAM_VALUE', MsgType.PARAM_VALUE):
                    try:
                        self._msg_queues[qt].clear()
                    except Exception:
                        pass
            else:
                # Legacy path: drain socket directly
                while True:
                    with self.master_lock:
                        msg = self.master.recv_match(
                            type=['PANDION_RR_PARAM_VALUE', MsgType.PARAM_VALUE],
                            blocking=False, timeout=0.01
                        )
                    if not msg:
                        break

            param_id_bytes = b'USE_NEST' + b'\x00' * (16 - len(b'USE_NEST'))

            with self.master_lock:
                self.master.mav.param_request_read_send(
                    self.master.target_system,
                    self.master.target_component,
                    param_id_bytes,
                    -1
                )

            timeout = 5.0
            start_time = time.monotonic()

            while time.monotonic() - start_time < timeout and not self.should_stop():
                # Pandion firmware responds with PANDION_RR_PARAM_VALUE,
                # not standard PARAM_VALUE.  Try custom first, fall back
                # to standard for SITL compatibility.
                msg = self._wait_for_message('PANDION_RR_PARAM_VALUE', timeout=0.1)
                if msg is None:
                    msg = self._wait_for_message(MsgType.PARAM_VALUE, timeout=0.1)

                if msg:
                    param_name = (
                        msg.param_id.decode('utf-8').rstrip('\x00')
                        if isinstance(msg.param_id, bytes)
                        else str(msg.param_id).rstrip('\x00')
                    )

                    if param_name == 'USE_NEST':
                        value = int(msg.param_value)
                        self.cb.on_log(f"  ✓ Received USE_NEST = {value}")
                        self.use_nest_cache = value
                        return value

            self.cb.on_log("  ⚠ USE_NEST query timeout after 5s")
            return None

        except Exception as e:
            self.cb.on_log(f"  ⚠ Error querying USE_NEST: {e}")
            return None
    
    def _set_use_nest(self, value: int) -> Tuple[bool, str]:
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
    
    def _clear_monitors_until_clean(self, timeout: float = 20.0) -> bool:
        """
        Poll and clear SET monitors until none remain or timeout expires.

        Unlike the old fixed-duration loop, this stops as soon as monitors
        are confirmed clear — avoiding unnecessary wait time when the vehicle
        is already in a clean state.

        Args:
            timeout: Maximum seconds to spend clearing (default 20s)

        Returns:
            bool: True if all monitors clear, False if timeout with monitors remaining
        """
        start = time.monotonic()
        consecutive_clean = 0
        required_clean_polls = 2  # Require 2 consecutive clean polls to confirm

        while time.monotonic() - start < timeout and not self.should_stop():
            current_set = self._get_current_set_monitors()

            if not current_set:
                consecutive_clean += 1
                if consecutive_clean >= required_clean_polls:
                    self.cb.on_log(
                        f"  ✓ All monitors clear (confirmed {required_clean_polls}x)"
                    )
                    return True
            else:
                consecutive_clean = 0
                self._clear_specific_monitors(current_set)

            time.sleep(0.3)

        remaining = self._get_current_set_monitors()
        if remaining:
            self.cb.on_log(
                f"  ⚠ Monitor clear timeout — {len(remaining)} monitors "
                f"still SET: {remaining}"
            )
            return False
        return True

    def _capture_current_state(self, state_obj: UUTState) -> Tuple[bool, str]:
        """Helper to capture the current state into a state object"""
        state_obj.timestamp = time.monotonic()

        try:
            state_obj.use_nest = self._query_use_nest()

            actuation_msg = self._wait_for_message(
                MsgType.ACTUATION_SYS_STATUS,
                timeout=2.0
            )
            state_obj.actuation_mode = (
                actuation_msg.actuation_state if actuation_msg else -1
            )

            pandion_status = self._wait_for_message(MsgType.PANDION_STATUS, timeout=2.0)
            if pandion_status:
                flight_regime = pandion_status.flight_regime
                state_obj.flight_regime = flight_regime
                state_obj.armed = is_armed(flight_regime)
            else:
                state_obj.armed = None
                state_obj.flight_regime = None

            monitor_msg = self._wait_for_message(
                MsgType.MONITOR_STATUS,
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

        except Exception as e:
            return False, f"Failed to capture state: {type(e).__name__}: {e}"
    
    def _wait_for_message(self, msg_type: str, timeout: float = 5.0) -> Optional[Any]:
        """
        Wait for a specific message type.

        When shared dispatch queues are available (injected via ``msg_queues``
        in __init__), reads from the per-type deque — no lock needed and no
        risk of stealing messages from other consumers.

        Falls back to direct socket access (short-poll, releases lock between
        checks) when running standalone without a dispatch worker.

        Also emits vehicle status signals for live UI updates during
        the preparation phase.

        Args:
            msg_type: Message type to wait for
            timeout: Timeout in seconds

        Returns:
            Message object or None if timeout
        """
        if self._msg_queues is not None:
            # Use shared dispatch queues (no lock needed)
            deadline = time.monotonic() + timeout
            q = self._msg_queues[msg_type]
            while time.monotonic() < deadline:
                if q:
                    msg = q.popleft()
                    self._emit_status_from_message(msg)
                    return msg
                remaining = deadline - time.monotonic()
                time.sleep(min(0.005, max(0.0, remaining)))
            return None
        else:
            # Legacy: direct socket access — short-poll to avoid holding lock
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                with self.master_lock:
                    msg = self.master.recv_match(type=msg_type, blocking=False)
                if msg:
                    self._emit_status_from_message(msg)
                    return msg
                remaining = deadline - time.monotonic()
                time.sleep(min(0.01, max(0.0, remaining)))
            return None

    def _emit_status_from_message(self, msg: Any) -> None:
        """Emit UI status signals from any received MAVLink message."""
        try:
            msg_type = msg.get_type()
            if msg_type == MsgType.PANDION_STATUS:
                fr = msg.flight_regime
                armed = is_armed(fr)
                self.cb.on_armed_state(armed, fr)
                self.cb.on_connection_health(True)
            elif msg_type == MsgType.ACTUATION_SYS_STATUS:
                self.cb.on_mode(msg.actuation_state)
                self.cb.on_connection_health(True)
                try:
                    global _build_actuator_feedback_dict
                    if _build_actuator_feedback_dict is None:
                        from testing.helpers import _build_actuator_feedback_dict
                    self.cb.on_actuator_feedback(_build_actuator_feedback_dict(msg))
                except (AttributeError, ImportError):
                    pass
            elif msg_type == 'HEARTBEAT':
                self.cb.on_connection_health(True)
        except Exception:
            pass