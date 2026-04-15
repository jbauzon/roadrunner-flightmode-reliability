"""Actuator feedback table with 8-surface display and stale indicator."""
from __future__ import annotations

from PyQt5.QtWidgets import QGroupBox, QVBoxLayout, QGridLayout
from PyQt5.QtCore import Qt
from datetime import datetime

from .. import theme as T
from .primitives import _label, _sep


class ActuatorFeedbackWidget(QGroupBox):
    def __init__(self, parent=None):
        super().__init__("Actuator Feedback", parent)
        self._feedback_cache = {}  # serial_number -> {data dict}
        self._current_serial = None
        self._is_stale = False
        self._last_data = None
        self._last_update_time = None
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 16, 12, 10)
        layout.setSpacing(6)

        # Header
        hdr = QGridLayout()
        hdr.setSpacing(4)
        for i, txt in enumerate(["Surface", "Feedback (\u00b0)", "Current (mA)", "Temp (\u00b0C)"]):
            lbl = _label(txt, T.TEXT_DISABLED, size=T.FONT_SIZE_SM)
            lbl.setAlignment(Qt.AlignCenter)
            hdr.addWidget(lbl, 0, i)
        layout.addLayout(hdr)
        layout.addWidget(_sep())

        # Rows
        surfaces = [
            ("L Elevon",    "left_elevon"),
            ("R Elevon",    "right_elevon"),
            ("Dorsal Rud",  "dorsal_rudder"),
            ("Ventral Rud", "ventral_rudder"),
            ("L TVC Up",    "left_tvc_upper"),
            ("L TVC Lo",    "left_tvc_lower"),
            ("R TVC Up",    "right_tvc_upper"),
            ("R TVC Lo",    "right_tvc_lower"),
        ]

        self._rows = {}
        self._grid = QGridLayout()
        self._grid.setSpacing(3)

        for row_idx, (display, key) in enumerate(surfaces):
            lbl = _label(display, T.TEXT_SECONDARY, size=T.FONT_SIZE_SM)
            self._grid.addWidget(lbl, row_idx, 0)

            fb   = _label("---", mono=True, size=T.FONT_SIZE_SM)
            curr = _label("---", mono=True, size=T.FONT_SIZE_SM)
            temp = _label("---", mono=True, size=T.FONT_SIZE_SM)

            for col_idx, w in enumerate([fb, curr, temp], start=1):
                w.setAlignment(Qt.AlignCenter)
                self._grid.addWidget(w, row_idx, col_idx)

            self._rows[key] = {'fb': fb, 'curr': curr, 'temp': temp}

        layout.addLayout(self._grid)

        self.last_update_label = _label("Last update: \u2014", T.TEXT_DISABLED, size=T.FONT_SIZE_SM)
        layout.addWidget(self.last_update_label)

    def update_feedback(self, data):
        """Update all surface rows from a feedback data dict."""
        self._is_stale = False
        self._last_data = data
        self._last_update_time = datetime.now().strftime('%H:%M:%S.%f')[:-4]
        try:
            keys = [
                "left_elevon", "right_elevon",
                "dorsal_rudder", "ventral_rudder",
                "left_tvc_upper", "left_tvc_lower",
                "right_tvc_upper", "right_tvc_lower",
            ]
            for key in keys:
                row = self._rows[key]
                fb_raw = data.get(f"{key}_feedback_cdeg")
                curr   = data.get(f"{key}_current_mA")
                temp   = data.get(f"{key}_motor_temp_degC")

                fb_deg = fb_raw / 100.0 if fb_raw is not None else None

                row['fb'].setText(f"{fb_deg:.1f}" if fb_deg is not None else "---")
                row['curr'].setText(str(curr) if curr is not None else "---")
                row['temp'].setText(str(temp) if temp is not None else "---")

            self.last_update_label.setText(
                f"Last update: {self._last_update_time}"
            )
            self.last_update_label.setStyleSheet(
                f"color: {T.TEXT_DISABLED}; font-size: {T.FONT_SIZE_SM};"
            )
        except Exception:
            pass

    def reset(self):
        """Clear all surface data to '---'."""
        for row in self._rows.values():
            for w in row.values():
                w.setText("---")
                w.setStyleSheet(
                    f"color: {T.TEXT_SECONDARY}; font-family: {T.FONT_MONO}; "
                    f"font-size: {T.FONT_SIZE_SM}; background: transparent;"
                )
        self.last_update_label.setText("Last update: \u2014")
        self.last_update_label.setStyleSheet(
            f"color: {T.TEXT_DISABLED}; font-size: {T.FONT_SIZE_SM};"
        )

    def set_current_uut(self, serial_number):
        """Switch to showing data for a specific UUT."""
        # Save current data to cache
        if self._current_serial and not self._is_stale and self._last_data:
            self._feedback_cache[self._current_serial] = self._last_data

        self._current_serial = serial_number

        # Load cached data for the new UUT
        cached = self._feedback_cache.get(serial_number)
        if cached:
            self._show_stale(cached)
        else:
            self.reset()

    def _show_stale(self, data):
        """Show cached data with stale indicator."""
        self._is_stale = True
        self.update_feedback(data)
        # Re-set stale flag (update_feedback clears it)
        self._is_stale = True
        # Dim all values and add stale indicator
        for row in self._rows.values():
            for w in row.values():
                current_style = w.styleSheet()
                w.setStyleSheet(current_style.replace(
                    f"color: {T.GREEN}", f"color: {T.TEXT_DISABLED}"
                ).replace(
                    f"color: {T.AMBER}", f"color: {T.TEXT_DISABLED}"
                ).replace(
                    f"color: {T.RED}", f"color: {T.TEXT_DISABLED}"
                ))
        self.last_update_label.setText(
            f"Last update: {self._last_update_time} (stale)"
        )
        self.last_update_label.setStyleSheet(
            f"color: {T.AMBER}; font-size: {T.FONT_SIZE_SM}; font-style: italic;"
        )
