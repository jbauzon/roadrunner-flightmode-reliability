from __future__ import annotations

"""
Flight Profile Playback Executor.
"""
import time
import csv
import threading
from typing import Any, Optional

from .base_executor import _ExecutorMixin
from .helpers import _build_actuator_feedback_dict
from .callbacks import ExecutorCallbacks
from vehicle.constants import (
    ActuationMode, MsgType,
    get_failed_surfaces,
)


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

            # Read feedback (non-blocking — use latest available from dispatch queue)
            fb = self._wait_for_message(
                'PANDION_RR_ACTUATION_SYS_STATUS',
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
