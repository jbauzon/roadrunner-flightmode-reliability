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
from rr_test.vehicle.constants import (
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
      2. Set CLASSIC_MODE_EN=1, USE_NEST=0
      3. ARM -> OPERATE -> PLAYBACK
      4. Enable load relay
      5. Stream PANDION_RR_PLAYBACK_COMMAND at 100 Hz from CSV
      6. Disable load relay
      7. Evaluate pass/fail (500 cdeg threshold per surface)
      8. Restore vehicle state (CLASSIC_MODE_EN=0, DISARM)
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
            if time.monotonic() >= self.batch_end_time:
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

            prep_ok, prep_msg = self.preparation.prepare_for_playback()
            if not prep_ok:
                raise Exception(prep_msg)

            # Enable load relay before streaming.  The relay applies
            # electrical load to the actuators during the test — it does
            # NOT control vehicle input power (that's a separate bench
            # supply the operator manages).
            self._enable_relay(label="playback test")

            # Start logging telemetry during active streaming
            if self.telemetry_logger:
                self.telemetry_logger.start_telemetry_stream()

            # Stream profile
            mistracking_flags, max_delta = self._stream_profile(profile)

            # Stop telemetry logging
            if self.telemetry_logger:
                self.telemetry_logger.stop_telemetry_stream()

            # S-13: Disable relay with failure check
            ok, disable_msg = self._set_line_with_timeout(self.uut.relay_line, False)
            if ok:
                self.cb.on_relay_state(False)
                if self.telemetry_logger:
                    self.telemetry_logger.log_relay_state(self.uut.relay_line, False)
                self.cb.on_log(f"\u2713 Relay {self.uut.relay_line} DISABLED")
            else:
                self.cb.on_log(
                    f"\u26a0 Relay disable failed: {disable_msg} \u2014 using emergency procedure"
                )
                self._emergency_relay_disable()

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

        Accepts two naming conventions:

          (A) Legacy "event/*" prefix + "_command_" infix (from AIQ tool):
            event/left_elevon_ted_command_cdeg
            event/left_engine_speed_command_prct_rpm
            ...

          (B) Production short names (as emitted by flight-test exports):
            left_elevon_ted_cdeg
            left_engine_prct_thrust
            ...

        Always required:
          timestamp

        Returns:
            List of dicts with canonical short keys — one dict per 100 Hz frame:
              left_elev, right_elev, low_rud, up_rud,
              l_tvc_up, l_tvc_lo, r_tvc_up, r_tvc_lo,
              l_eng, r_eng
        """
        # Each canonical key maps to a list of acceptable source column names.
        # The first match wins.
        COLUMN_ALIASES = {
            'left_elev': [
                'event/left_elevon_ted_command_cdeg',
                'left_elevon_ted_cdeg',
            ],
            'right_elev': [
                'event/right_elevon_ted_command_cdeg',
                'right_elevon_ted_cdeg',
            ],
            'low_rud': [
                'event/lower_rudder_tel_command_cdeg',
                'lower_rudder_tel_cdeg',
            ],
            'up_rud': [
                'event/upper_rudder_tel_command_cdeg',
                'upper_rudder_tel_cdeg',
            ],
            'l_tvc_up': [
                'event/left_tvc_upper_command_cdeg',
                'left_tvc_upper_cdeg',
            ],
            'l_tvc_lo': [
                'event/left_tvc_lower_command_cdeg',
                'left_tvc_lower_cdeg',
            ],
            'r_tvc_up': [
                'event/right_tvc_upper_command_cdeg',
                'right_tvc_upper_cdeg',
            ],
            'r_tvc_lo': [
                'event/right_tvc_lower_command_cdeg',
                'right_tvc_lower_cdeg',
            ],
            'l_eng': [
                'event/left_engine_speed_command_prct_rpm',
                'left_engine_prct_thrust',
                'left_engine_speed_prct_thrust',
            ],
            'r_eng': [
                'event/right_engine_speed_command_prct_rpm',
                'right_engine_prct_thrust',
                'right_engine_speed_prct_thrust',
            ],
        }

        with open(csv_path, newline='') as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                raise ValueError("CSV has no header row")
            fieldnames = reader.fieldnames

            # Timestamp is always required
            if 'timestamp' not in fieldnames:
                raise ValueError("CSV missing required column: timestamp")

            # Resolve each canonical key to an actual column name
            col_map = {}
            missing = []
            for canonical, aliases in COLUMN_ALIASES.items():
                found = next((a for a in aliases if a in fieldnames), None)
                if found is None:
                    missing.append(f"{canonical} (tried: {aliases})")
                else:
                    col_map[canonical] = found

            if missing:
                raise ValueError(
                    f"CSV missing required columns: {missing}\n"
                    f"  Available columns: {fieldnames}"
                )

            # Read raw rows
            raw_rows = list(reader)

        if not raw_rows:
            raise ValueError("CSV profile is empty")

        # Normalize each row to the canonical short-key form (with timestamp
        # parsed to a float for the resampling step below)
        parsed: list[dict] = []
        for i, raw in enumerate(raw_rows):
            try:
                row: dict = {'timestamp': float(raw['timestamp'])}
                for canonical, src_col in col_map.items():
                    row[canonical] = float(raw[src_col] or 0.0)
                parsed.append(row)
            except (ValueError, KeyError) as e:
                # Skip malformed rows silently — they'll show in the frame-
                # error log during streaming if they matter
                self.cb.on_log(f"  \u26a0 Row {i} parse error (skipped): {e}")

        if not parsed:
            raise ValueError("CSV profile had no valid rows after parsing")

        # ── Rate detection + resampling to 100 Hz ───────────────────────
        # The firmware consumes PANDION_RR_PLAYBACK_COMMAND at a fixed
        # 100 Hz actuation task rate.  If the CSV was recorded at a
        # different rate (e.g. NominalFlight_noRudder.csv is recorded at
        # 500 Hz with 2ms timestamp deltas in milliseconds), we must
        # resample so the vehicle sees the same flight at the same
        # wall-clock duration it was recorded at — NOT 5x slower.
        #
        # Rate detection: look at the median dt between the first ~50
        # samples, then guess the timestamp unit.
        rows = self._resample_to_100hz(parsed)

        self.cb.on_log(f"  CSV columns ({len(fieldnames)}): {fieldnames}")
        self.cb.on_log(f"  Column mapping: {col_map}")
        return rows

    # ----------------------------------------------------------
    # Rate detection + resampling
    # ----------------------------------------------------------

    _PLAYBACK_RATE_HZ = 100.0   # firmware-fixed, do not change

    def _resample_to_100hz(self, parsed: list[dict]) -> list[dict]:
        """Resample a CSV's rows to exactly 100 Hz by timestamp.

        The firmware's actuation task runs at 100 Hz and consumes
        ``PANDION_RR_PLAYBACK_COMMAND`` at that rate; sending faster is
        wasteful (frames get dropped by the vehicle) and slower stretches
        the flight (e.g. a 65 s flight becomes 5.5 min of near-static
        commands).

        Strategy:
          1. Detect the source sample rate from the median timestamp
             delta between the first ~50 rows.
          2. Guess the timestamp unit (seconds / milliseconds /
             microseconds) by which one yields a plausible rate
             (>= 10 Hz and <= 10000 Hz).
          3. If the source rate is within 5% of 100 Hz, pass through
             unchanged.
          4. Otherwise, walk the input at 10 ms steps (in whatever the
             native timestamp unit turned out to be) and pick the
             nearest-in-timestamp source sample for each output frame.

        Returns a list of dicts ready for streaming, one per 100 Hz
        frame.  The ``timestamp`` field is rewritten to the resampled
        index in seconds (so progress/stats are consistent).
        """
        n = len(parsed)
        if n < 2:
            return parsed

        # Median dt from first 50 rows (or all rows if fewer)
        sample_n = min(50, n - 1)
        dts = sorted(
            parsed[i + 1]['timestamp'] - parsed[i]['timestamp']
            for i in range(sample_n)
        )
        median_dt = dts[sample_n // 2]
        if median_dt <= 0:
            self.cb.on_log(
                "  \u26a0 Could not detect CSV timestamp rate "
                "(non-monotonic timestamps) — streaming every row at 100 Hz")
            return parsed

        # Try each unit and pick the one that gives a plausible rate
        # (>= 10 Hz, <= 10000 Hz).  Most flight profiles record at
        # 100 Hz, 200 Hz, 500 Hz, or 1 kHz.
        units = [
            ("seconds",     1.0),
            ("milliseconds", 1e-3),
            ("microseconds", 1e-6),
        ]
        detected_unit = None
        detected_rate = 0.0
        for name, unit_s in units:
            rate = 1.0 / (median_dt * unit_s)
            if 10.0 <= rate <= 10000.0:
                detected_unit = name
                detected_rate = rate
                detected_unit_s = unit_s
                break

        if detected_unit is None:
            self.cb.on_log(
                f"  \u26a0 Could not detect CSV timestamp unit "
                f"(median dt = {median_dt}; expected sub-second).  "
                f"Streaming every row at 100 Hz.")
            return parsed

        # Rate within 5% of 100 Hz — pass through, no resampling needed
        if abs(detected_rate - self._PLAYBACK_RATE_HZ) / self._PLAYBACK_RATE_HZ < 0.05:
            self.cb.on_log(
                f"  CSV recorded at {detected_rate:.1f} Hz "
                f"(timestamp unit: {detected_unit}) — matches 100 Hz "
                f"playback rate, no resampling needed")
            return parsed

        # Resample: pick the nearest source sample at each 10 ms step.
        # Walk output index j = 0, 1, 2, ... and source index i (advances
        # monotonically).
        ts0 = parsed[0]['timestamp']
        ts_last = parsed[-1]['timestamp']
        duration_s = (ts_last - ts0) * detected_unit_s
        interval_native = (1.0 / self._PLAYBACK_RATE_HZ) / detected_unit_s
        output_n = int(duration_s * self._PLAYBACK_RATE_HZ) + 1

        resampled: list[dict] = []
        i = 0
        for j in range(output_n):
            target_ts = ts0 + j * interval_native
            # Advance i while next sample is closer to target
            while i + 1 < n:
                d_here = abs(parsed[i]['timestamp'] - target_ts)
                d_next = abs(parsed[i + 1]['timestamp'] - target_ts)
                if d_next < d_here:
                    i += 1
                else:
                    break
            row = dict(parsed[i])          # copy to avoid aliasing
            row['timestamp'] = j / self._PLAYBACK_RATE_HZ  # rewrite to seconds
            resampled.append(row)

        self.cb.on_log(
            f"  CSV recorded at {detected_rate:.0f} Hz "
            f"(timestamp unit: {detected_unit}, duration {duration_s:.1f}s).  "
            f"Resampled from {n} \u2192 {len(resampled)} frames at 100 Hz "
            f"so the flight plays back at its original speed.")
        return resampled

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
        # Absolute-time schedule: frame N's target send time is start + N*interval.
        # Per-frame relative pacing ("sleep interval - elapsed") can't recover
        # from any frame that overruns its 10 ms budget, accumulating drift.
        # Over 32808 frames even 0.75 ms jitter per frame adds 25 s of lag.
        stream_start = time.time()

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

        # UI callback rate limiters: at 100 Hz the playback loop generates
        # 100 actuator_feedback + 100 test_duration callbacks per UUT per
        # second, which saturates the WebSocket broadcast path. The UI
        # doesn't need higher than ~10 Hz for these human-visible updates.
        UI_FEEDBACK_PERIOD_S = 0.1   # 10 Hz for actuator feedback
        UI_DURATION_PERIOD_S = 0.5   # 2 Hz for duration text
        _last_ui_feedback_t = 0.0
        _last_ui_duration_t = 0.0

        for frame_idx, row in enumerate(profile):
            if not self.running:
                self.cb.on_log("⚠ Playback stopped by user")
                break

            # Parse commands — rows are already normalized to canonical short
            # keys by _load_profile (accepts both 'event/*_command_*' legacy
            # format and production short names like 'left_elevon_ted_cdeg').
            try:
                cmds = {
                    'left_elev':  float(row['left_elev']),
                    'right_elev': float(row['right_elev']),
                    'low_rud':    float(row['low_rud']),
                    'up_rud':     float(row['up_rud']),
                    'l_tvc_up':   float(row['l_tvc_up']),
                    'l_tvc_lo':   float(row['l_tvc_lo']),
                    'r_tvc_up':   float(row['r_tvc_up']),
                    'r_tvc_lo':   float(row['r_tvc_lo']),
                    'l_eng':      float(row['l_eng']),
                    'r_eng':      float(row['r_eng']),
                }
            except (ValueError, KeyError) as e:
                self.cb.on_log(f"\u26a0 Frame {frame_idx} parse error: {e}")
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

            # Drain any feedback messages from the dispatch queue without
            # blocking. At 100 Hz loop rate vs 5 Hz feedback, most iterations
            # will find nothing. Consume ALL available messages so deltas
            # reflect the freshest feedback and the queue doesn't grow
            # unbounded (capped at maxlen=100 but still).
            fb = None
            if self._msg_queues is not None:
                q = self._msg_queues['PANDION_RR_ACTUATION_SYS_STATUS']
                while q:
                    fb = q.popleft()  # keep the latest
            else:
                fb = self._wait_for_message(
                    'PANDION_RR_ACTUATION_SYS_STATUS', timeout=0.001
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

                # Emit to UI (throttled to ~10 Hz — 100 Hz saturates WS broadcast)
                now_ui = time.time()
                if now_ui - _last_ui_feedback_t >= UI_FEEDBACK_PERIOD_S:
                    _last_ui_feedback_t = now_ui
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

            # Duration update (throttled to ~2 Hz)
            if self.uut.test_start_time:
                now_ui2 = time.time()
                if now_ui2 - _last_ui_duration_t >= UI_DURATION_PERIOD_S:
                    _last_ui_duration_t = now_ui2
                    self.cb.on_test_duration(
                        now_ui2 - self.uut.test_start_time
                    )

            # Pace to 100 Hz using absolute-time schedule. The next frame's
            # target send time is stream_start + (frame_idx+1) * interval.
            # Sleeping to the absolute target keeps the overall average rate
            # at exactly 100 Hz even if individual frames overrun.
            next_target = stream_start + (frame_idx + 1) * interval
            remaining = next_target - time.time()
            if remaining > 0:
                time.sleep(remaining)

        total_elapsed = time.time() - self.uut.test_start_time if self.uut.test_start_time else 0.0
        actual_hz = (len(profile) / total_elapsed) if total_elapsed > 0 else 0.0
        self.cb.on_log(
            f"\n✓ Profile streaming complete — "
            f"{len(profile)} frames, "
            f"mistracking_flags=0x{accumulated_flags:02X}"
        )
        self.cb.on_log(
            f"  Streaming stats: {total_elapsed:.1f}s total, "
            f"{actual_hz:.1f} fps (target 100 Hz)"
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

        The firmware only populates ``actuation_ibit_mon_status`` during
        IBIT mode (see ``send_actuation_system_status_packet`` in
        ``vehicle/mavlink/mavlink.c``) — outside IBIT, that field is
        reset to ``PANDION_RR_IBIT_STATUS_NONE`` each cycle.  So during
        Playback we can't rely on the firmware bitmask for PASS/FAIL.

        Instead we mirror the firmware's own threshold check ourselves:
        any surface whose peak command-vs-feedback delta exceeded
        500 cdeg (= ``IBIT_TVC_SERVO_TRACKING_MAX_DELTA_CDEG`` in
        ``vehicle/actuation/actuation.c``) is flagged.

        Pass criteria:
          - Firmware bitmask is 0 (always true in Playback; check
            kept for defense in depth)
          - AND all ``max_deltas[surface]`` are <= 500 cdeg

        Returns:
            (success: bool, message: str)
        """
        self.cb.on_log("\n" + "=" * 60)
        self.cb.on_log("PLAYBACK RESULT EVALUATION")
        self.cb.on_log("=" * 60)

        THRESHOLD_CDEG = 500.0  # matches firmware IBIT_TVC_SERVO_TRACKING_MAX_DELTA_CDEG

        # Log max deltas and identify surfaces exceeding threshold
        self.cb.on_log("Max command-feedback deltas (threshold: 500 cdeg):")
        failed_by_delta = []
        for surface, delta in max_deltas.items():
            marker = "  FAIL" if delta > THRESHOLD_CDEG else "    ok"
            self.cb.on_log(f"  {marker}  {surface:25s}: {delta:.1f} cdeg")
            if delta > THRESHOLD_CDEG:
                failed_by_delta.append(surface)

        # Evaluate both signals
        has_fw_flag = mistracking_flags != 0
        has_delta_fail = bool(failed_by_delta)

        if not has_fw_flag and not has_delta_fail:
            self.cb.on_log("\n✓ PASS — All surfaces tracked within 500 cdeg threshold")
            self.telemetry_logger.log_test_event(
                'PLAYBACK_PASS',
                f'All surfaces tracked correctly — max_deltas={max_deltas}'
            )
            return True, "Playback PASS — all surfaces tracked correctly"

        # Assemble failure reason
        parts = []
        if has_fw_flag:
            fw_failed = get_failed_surfaces(mistracking_flags)
            parts.append(f"firmware flags: {', '.join(fw_failed)}")
            self.cb.on_log(f"\n✗ Firmware mistracking flags set: 0x{mistracking_flags:02X}")
        if has_delta_fail:
            parts.append(f"delta > 500 cdeg: {', '.join(failed_by_delta)}")
            self.cb.on_log(f"\n✗ Surfaces exceeding 500 cdeg threshold:")
            for surface in failed_by_delta:
                self.cb.on_log(f"    {surface}: {max_deltas[surface]:.1f} cdeg")

        msg = f"Playback FAIL — {'; '.join(parts)}"
        self.telemetry_logger.log_test_event(
            'PLAYBACK_FAIL',
            f'{msg} — fw_flags=0x{mistracking_flags:02X} max_deltas={max_deltas}'
        )
        return False, msg

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
                    "  ✓ CLASSIC_MODE_EN restored to 0"
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
