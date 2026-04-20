"""
Telemetry Logger — clean, human-readable CSV logging.

Two log files per UUT per day:

  events.csv     One row per meaningful event (start, armed, phase
                 transition, pass/fail, disarm).  An operator reads this.

  telemetry.csv  Raw 5 Hz actuator positions + currents during the active
                 test phase (IBIT or Playback streaming).  For post-test
                 analysis, not for humans to scroll through.

Files are created in <log_directory>/<date>/<serial>/.
"""
from __future__ import annotations

import csv
import os
import time
from datetime import datetime
from typing import Any, Optional

from rr_test.vehicle.constants import (
    ACTUATION_MODE_NAMES,
    FLIGHT_REGIME_NAMES,
    get_flight_regime_name,
    is_armed,
)

import logging

_log = logging.getLogger(__name__)


class TelemetryLogger:
    """Per-UUT logger that writes events.csv and telemetry.csv."""

    def __init__(
        self,
        log_directory: str,
        uut_serial: str,
        test_start_datetime: Any = None,
        logging_mode: str = "ibit_focused",
        max_file_size_mb: int = 100,
        test_mode: str = "ibit",
        on_log: Any = None,
        on_file_rotated: Any = None,
    ) -> None:
        self._on_log = on_log or (lambda msg: None)
        self.uut_serial = uut_serial
        self.test_mode = test_mode
        self.logging_mode = logging_mode
        self.iteration_number = 0

        # Create directory: logs/<date>/<serial>/
        date_str = datetime.now().strftime("%Y-%m-%d")
        self._dir = os.path.join(log_directory, date_str, uut_serial)
        os.makedirs(self._dir, exist_ok=True)

        # Event log — append mode so multiple iterations go in one file
        self._event_path = os.path.join(self._dir, "events.csv")
        write_event_header = not os.path.isfile(self._event_path)
        self._event_file = open(self._event_path, "a", newline="")
        self._event_writer = csv.writer(self._event_file)
        if write_event_header:
            self._event_writer.writerow([
                "Timestamp", "Iteration", "Event", "Result", "Details",
            ])
            self._event_file.flush()

        # Telemetry log — one file per iteration (overwritten each iter)
        self._telem_file: Optional[Any] = None
        self._telem_writer: Optional[csv.writer] = None
        self._telem_active = False

    # ── Event logging ─────────────────────────────────────────────────

    def log_test_event(self, event_type: str, description: str = "") -> None:
        """Log a meaningful test event (one row)."""
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._event_writer.writerow([
            ts, self.iteration_number, event_type, "", description,
        ])
        self._event_file.flush()

    def log_result(self, passed: bool, details: str = "") -> None:
        """Log a PASS/FAIL result."""
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        result = "PASS" if passed else "FAIL"
        self._event_writer.writerow([
            ts, self.iteration_number, "RESULT", result, details,
        ])
        self._event_file.flush()

    def log_relay_state(self, relay_line: Any, state: bool) -> None:
        """Log relay state change."""
        self.log_test_event(
            "RELAY_ON" if state else "RELAY_OFF",
            f"Relay {relay_line} {'ON' if state else 'OFF'}",
        )

    # ── Telemetry streaming ───────────────────────────────────────────

    def start_telemetry_stream(self) -> None:
        """Open a new telemetry CSV for the current iteration."""
        path = os.path.join(
            self._dir,
            f"telemetry_iter{self.iteration_number:03d}.csv",
        )
        self._telem_file = open(path, "w", newline="")
        self._telem_writer = csv.writer(self._telem_file)
        self._telem_writer.writerow([
            "Timestamp",
            "Mode", "Substate", "Regime", "Armed",
            "L_Elevon_cdeg", "R_Elevon_cdeg",
            "Dorsal_Rud_cdeg", "Ventral_Rud_cdeg",
            "L_TVC_Up_cdeg", "L_TVC_Lo_cdeg",
            "R_TVC_Up_cdeg", "R_TVC_Lo_cdeg",
            "L_Elev_mA", "R_Elev_mA",
            "Dors_Rud_mA", "Vent_Rud_mA",
            "L_TVC_Up_mA", "L_TVC_Lo_mA",
            "R_TVC_Up_mA", "R_TVC_Lo_mA",
            "Mistracking_Flags",
        ])
        self._telem_active = True

    def stop_telemetry_stream(self) -> None:
        """Close the telemetry CSV."""
        self._telem_active = False
        if self._telem_file:
            self._telem_file.close()
            self._telem_file = None
            self._telem_writer = None

    def log_telemetry(self, msg: Any) -> None:
        """Log a single MAVLink message to the telemetry CSV.

        Only writes PANDION_RR_ACTUATION_SYS_STATUS rows during an active
        telemetry stream (between start/stop_telemetry_stream).  All other
        message types and all messages outside the stream window are ignored.
        """
        if not self._telem_active or not self._telem_writer:
            return

        if msg.get_type() != "PANDION_RR_ACTUATION_SYS_STATUS":
            return

        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        mode = ACTUATION_MODE_NAMES.get(
            getattr(msg, "actuation_state", -1), "?"
        )
        sub = getattr(msg, "actuation_ibit_substate", "")
        regime = getattr(msg, "flight_regime", "")
        armed = is_armed(regime) if isinstance(regime, int) else ""
        flags = getattr(msg, "actuation_ibit_mon_status", 0)

        self._telem_writer.writerow([
            ts, mode, sub, regime, armed,
            getattr(msg, "left_elevon_feedback_cdeg", ""),
            getattr(msg, "right_elevon_feedback_cdeg", ""),
            getattr(msg, "dorsal_rudder_feedback_cdeg", ""),
            getattr(msg, "ventral_rudder_feedback_cdeg", ""),
            getattr(msg, "left_tvc_upper_feedback_cdeg", ""),
            getattr(msg, "left_tvc_lower_feedback_cdeg", ""),
            getattr(msg, "right_tvc_upper_feedback_cdeg", ""),
            getattr(msg, "right_tvc_lower_feedback_cdeg", ""),
            getattr(msg, "left_elevon_current_mA", ""),
            getattr(msg, "right_elevon_current_mA", ""),
            getattr(msg, "dorsal_rudder_current_mA", ""),
            getattr(msg, "ventral_rudder_current_mA", ""),
            getattr(msg, "left_tvc_upper_current_mA", ""),
            getattr(msg, "left_tvc_lower_current_mA", ""),
            getattr(msg, "right_tvc_upper_current_mA", ""),
            getattr(msg, "right_tvc_lower_current_mA", ""),
            f"0x{flags:02X}" if flags else "",
        ])

    # ── Lifecycle ─────────────────────────────────────────────────────

    def close(self) -> None:
        """Flush and close all files."""
        self.stop_telemetry_stream()
        if self._event_file:
            self._event_file.close()
            self._event_file = None

    # ── Compat stubs (called by existing executor code) ───────────────
    # These methods exist so existing code that calls logger.update_*
    # doesn't crash.  The new logger doesn't need per-field state
    # tracking because events and telemetry are separate files.

    def update_ibit_phase(self, substate: int) -> None:
        pass

    def update_armed_state(self, armed: bool, flight_regime: int) -> None:
        pass

    def open(self) -> bool:
        """Compat: files are opened in __init__, so this is a no-op."""
        return True

    def set_iteration_number(self, n: int) -> None:
        self.iteration_number = n

    def get_current_log_path(self) -> str:
        return self._event_path

    # Class-level constants for compat
    MODE_IBIT_FOCUSED = "ibit_focused"
    MODE_NONE = "none"
