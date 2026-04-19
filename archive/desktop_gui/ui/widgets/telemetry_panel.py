"""
ui.widgets.telemetry_panel -- Live UUT telemetry display for debug mode.

Shows real-time MAVLink telemetry from the connected vehicle:
- Vehicle Status (mode, flight regime, armed state, relay state)
- IBIT Status (substate, mistracking flags accumulated)
- Actuator Surfaces (all 8: feedback position, current, temp)
- Battery (pack voltage, current, SoC)
- Engine (RPM, EGT, fuel pump)
- Connection (heartbeat count, link quality, sysid)
- Raw message stream (last 20 messages received, type + key fields)
"""
from __future__ import annotations

from datetime import datetime

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QScrollArea, QListWidget, QListWidgetItem,
    QProgressBar, QFrame, QSizePolicy,
)
from PyQt5.QtCore import Qt

from .. import theme as T
from .primitives import StatusBadge, LED, _label, _sep, _section_title
from rr_test.vehicle.constants import ActuationMode, get_mode_name, get_flight_regime_short_name


# ── Surface name / flag bit mapping (matches actuator_feedback.py) ─────────────
_SURFACE_FLAGS = [
    (64,  "L Elevon"),
    (128, "R Elevon"),
    (1,   "Dorsal Rud"),
    (2,   "Ventral Rud"),
    (4,   "L TVC Up"),
    (8,   "L TVC Lo"),
    (16,  "R TVC Up"),
    (32,  "R TVC Lo"),
]

_SURFACE_KEYS = [
    "left_elevon",
    "right_elevon",
    "dorsal_rudder",
    "ventral_rudder",
    "left_tvc_upper",
    "left_tvc_lower",
    "right_tvc_upper",
    "right_tvc_lower",
]

# Message-type color coding for the stream list
_MSG_TYPE_COLORS = {
    "PANDION_RR_ACTUATION_FEEDBACK":  T.GREEN,
    "PANDION_RR_ACTUATION_STATE":     T.GREEN,
    "PANDION_VEHICLE_STATUS":         T.BLUE,
    "PANDION_IBIT_STATUS":            T.AMBER,
    "PANDION_ENGINE_STATUS":          T.ORANGE,
    "BATTERY_STATUS":                 T.TEAL,
    "HEARTBEAT":                      T.TEXT_SECONDARY,
    "COMMAND_ACK":                    T.PURPLE,
    "PARAM_VALUE":                    T.TEXT_SECONDARY,
}
_MSG_MAX = 20


def _mono_label(text: str = "---") -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"color: {T.TEXT_PRIMARY}; font-family: {T.FONT_MONO}; "
        f"font-size: {T.FONT_SIZE_SM}; background: transparent;"
    )
    lbl.setAlignment(Qt.AlignCenter)
    return lbl


def _bar_widget(color: str = T.BLUE) -> QProgressBar:
    bar = QProgressBar()
    bar.setRange(0, 100)
    bar.setValue(0)
    bar.setTextVisible(False)
    bar.setFixedHeight(8)
    bar.setStyleSheet(
        f"QProgressBar {{ background: {T.BG_BASE}; border: 1px solid {T.BORDER}; "
        f"border-radius: 4px; }}"
        f"QProgressBar::chunk {{ background: {color}; border-radius: 4px; }}"
    )
    return bar


class TelemetryPanelWidget(QWidget):
    """
    Live telemetry panel shown in Debug Mode.

    Accepts push-style updates via the public update_* methods, which are
    wired to QtExecutorBridge signals in main_window._wire_executor().
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mistracking_flags = 0
        self._last_mode = 0
        self._last_armed = False
        self._last_regime = 0
        self._msg_count = 0
        self._connected = False
        self._init_ui()

    # ── UI construction ───────────────────────────────────────────────────────

    def _section(self, title: str, color: str = None) -> tuple:
        """Create a section with a colored header bar. Returns (container, content_layout)."""
        color = color or T.TEXT_SECONDARY
        container = QWidget()
        container.setStyleSheet(
            f"QWidget {{ background: {T.BG_ELEVATED}; border-radius: 6px; }}"
        )
        outer = QVBoxLayout(container)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Header bar with left accent
        header = QWidget()
        header.setFixedHeight(28)
        header.setStyleSheet(
            f"background: transparent; "
            f"border-left: 3px solid {color}; "
            f"border-radius: 0; padding-left: 8px;"
        )
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(8, 0, 8, 0)
        lbl = QLabel(title.upper())
        lbl.setStyleSheet(
            f"color: {color}; font-size: {T.FONT_SIZE_SM}; "
            f"font-weight: bold; letter-spacing: 1px; background: transparent;"
        )
        header_layout.addWidget(lbl)
        header_layout.addStretch()
        outer.addWidget(header)

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(12, 4, 12, 10)
        content_layout.setSpacing(4)
        outer.addWidget(content)

        return container, content_layout

    def _init_ui(self) -> None:
        self.setStyleSheet(f"background: {T.BG_BASE};")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Scroll area wraps everything so narrow windows don't clip content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(f"background: {T.BG_BASE}; border: none;")

        inner = QWidget()
        inner.setStyleSheet(f"background: {T.BG_BASE};")
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # "Not connected" overlay shown when no vehicle data
        self._not_connected_label = QLabel(
            "No vehicle connected\nStart a test to see live telemetry"
        )
        self._not_connected_label.setAlignment(Qt.AlignCenter)
        self._not_connected_label.setStyleSheet(
            f"color: {T.TEXT_DISABLED}; font-size: 14pt; background: transparent;"
        )
        layout.addWidget(self._not_connected_label)

        # Build sections and track them for show/hide
        self._sections = []

        s = self._build_vehicle_status()
        self._sections.append(s)
        layout.addWidget(s)

        s = self._build_ibit_section()
        self._sections.append(s)
        layout.addWidget(s)

        s = self._build_actuator_table()
        self._sections.append(s)
        layout.addWidget(s)

        s = self._build_battery_section()
        self._sections.append(s)
        layout.addWidget(s)

        s = self._build_engine_section()
        self._sections.append(s)
        layout.addWidget(s)

        s = self._build_connection_section()
        self._sections.append(s)
        layout.addWidget(s)

        s = self._build_message_stream()
        self._sections.append(s)
        layout.addWidget(s, 1)

        # Start hidden until first real data
        for sec in self._sections:
            sec.hide()

        scroll.setWidget(inner)
        outer.addWidget(scroll)

    # ── Section builders ──────────────────────────────────────────────────────

    def _build_vehicle_status(self) -> QWidget:
        container, cl = self._section("Vehicle Status", T.GREEN)

        grid = QGridLayout()
        grid.setSpacing(8)
        grid.setColumnStretch(2, 1)

        # Mode
        grid.addWidget(_label("Mode", T.TEXT_SECONDARY), 0, 0)
        self._mode_badge = StatusBadge("---")
        self._mode_badge.set_color(T.BG_BASE, T.TEXT_DISABLED)
        self._mode_badge.setMinimumWidth(120)
        grid.addWidget(self._mode_badge, 0, 1, 1, 2)

        # Flight Regime
        grid.addWidget(_label("Regime", T.TEXT_SECONDARY), 1, 0)
        self._regime_label = _label("---", T.TEXT_PRIMARY)
        grid.addWidget(self._regime_label, 1, 1, 1, 2)

        # Armed
        grid.addWidget(_label("Armed", T.TEXT_SECONDARY), 2, 0)
        self._armed_led = LED()
        self._armed_label = StatusBadge("DISARMED")
        self._armed_label.set_color(T.GREEN_DIM, T.GREEN)
        grid.addWidget(self._armed_led, 2, 1)
        grid.addWidget(self._armed_label, 2, 2)

        # Relay
        grid.addWidget(_label("Relay", T.TEXT_SECONDARY), 3, 0)
        self._relay_led = LED()
        self._relay_led.set_state(None)
        self._relay_label = StatusBadge("UNKNOWN")
        self._relay_label.set_color(T.BG_ELEVATED, T.TEXT_DISABLED)
        grid.addWidget(self._relay_led, 3, 1)
        grid.addWidget(self._relay_label, 3, 2)

        cl.addLayout(grid)
        return container

    def _build_ibit_section(self) -> QWidget:
        container, cl = self._section("IBIT Status", T.AMBER)

        # Substate
        row1 = QHBoxLayout()
        row1.addWidget(_label("Substate", T.TEXT_SECONDARY))
        self._ibit_substate = _label("IDLE", T.TEXT_DISABLED)
        self._ibit_substate.setStyleSheet(
            f"color: {T.TEXT_DISABLED}; font-family: {T.FONT_MONO}; "
            f"font-weight: bold; font-size: {T.FONT_SIZE_SM}; background: transparent;"
        )
        row1.addWidget(self._ibit_substate)
        row1.addStretch()
        cl.addLayout(row1)

        # Mistracking surface indicators
        cl.addWidget(_label("Surface Tracking", T.TEXT_SECONDARY, size=T.FONT_SIZE_SM))
        surf_row = QHBoxLayout()
        surf_row.setSpacing(4)
        self._ibit_surface_labels: dict[int, QLabel] = {}
        for bit, name in _SURFACE_FLAGS:
            lbl = QLabel(name)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet(
                f"color: {T.TEXT_DISABLED}; font-size: 8pt; "
                f"background: {T.BG_BASE}; border: 1px solid {T.BORDER}; "
                f"border-radius: 3px; padding: 1px 3px;"
            )
            lbl.setFixedHeight(20)
            lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            surf_row.addWidget(lbl)
            self._ibit_surface_labels[bit] = lbl
        cl.addLayout(surf_row)

        return container

    def _build_actuator_table(self) -> QWidget:
        container, cl = self._section("Actuator Surfaces", T.BLUE)

        # Header row
        hdr = QGridLayout()
        hdr.setSpacing(2)
        for col, txt in enumerate(["Surface", "Pos (°)", "Current (mA)", "Temp (°C)"]):
            lbl = _label(txt, T.TEXT_DISABLED, size=T.FONT_SIZE_SM)
            lbl.setAlignment(Qt.AlignCenter)
            hdr.addWidget(lbl, 0, col)
        cl.addLayout(hdr)
        cl.addWidget(_sep())

        surface_display_names = [
            "L Elevon", "R Elevon", "Dorsal Rud", "Ventral Rud",
            "L TVC Up", "L TVC Lo", "R TVC Up", "R TVC Lo",
        ]

        self._actuator_rows: dict[str, dict] = {}
        grid = QGridLayout()
        grid.setSpacing(2)
        for row_idx, (key, display) in enumerate(zip(_SURFACE_KEYS, surface_display_names)):
            name_lbl = _label(display, T.TEXT_SECONDARY, size=T.FONT_SIZE_SM)
            fb_lbl   = _mono_label()
            curr_lbl = _mono_label()
            temp_lbl = _mono_label()
            grid.addWidget(name_lbl, row_idx, 0)
            grid.addWidget(fb_lbl,   row_idx, 1)
            grid.addWidget(curr_lbl, row_idx, 2)
            grid.addWidget(temp_lbl, row_idx, 3)
            self._actuator_rows[key] = {
                'name': name_lbl, 'fb': fb_lbl,
                'curr': curr_lbl, 'temp': temp_lbl,
            }
        cl.addLayout(grid)
        return container

    def _build_battery_section(self) -> QWidget:
        container, cl = self._section("Battery", T.GREEN)

        grid = QGridLayout()
        grid.setSpacing(6)
        grid.setColumnStretch(1, 1)

        # Voltage
        grid.addWidget(_label("Voltage", T.TEXT_SECONDARY), 0, 0)
        self._batt_voltage_lbl = _label("---  V", T.TEXT_PRIMARY, mono=True)
        grid.addWidget(self._batt_voltage_lbl, 0, 2)

        # Current
        grid.addWidget(_label("Current", T.TEXT_SECONDARY), 1, 0)
        self._batt_current_lbl = _label("---  A", T.TEXT_PRIMARY, mono=True)
        grid.addWidget(self._batt_current_lbl, 1, 2)

        # SoC bar + value
        grid.addWidget(_label("SoC", T.TEXT_SECONDARY), 2, 0)
        self._batt_soc_bar = _bar_widget(T.GREEN)
        grid.addWidget(self._batt_soc_bar, 2, 1)
        self._batt_soc_lbl = _label("---%", T.TEXT_PRIMARY, mono=True)
        grid.addWidget(self._batt_soc_lbl, 2, 2)

        cl.addLayout(grid)
        return container

    def _build_engine_section(self) -> QWidget:
        container, cl = self._section("Engine", T.ORANGE)

        grid = QGridLayout()
        grid.setSpacing(8)

        grid.addWidget(_label("Eng 1 RPM", T.TEXT_SECONDARY), 0, 0)
        self._eng_rpm_lbl = _label("---", T.TEXT_PRIMARY, mono=True)
        grid.addWidget(self._eng_rpm_lbl, 0, 1)

        grid.addWidget(_label("EGT", T.TEXT_SECONDARY), 1, 0)
        self._eng_egt_lbl = _label("---  °C", T.TEXT_PRIMARY, mono=True)
        grid.addWidget(self._eng_egt_lbl, 1, 1)

        grid.addWidget(_label("Fuel Pump", T.TEXT_SECONDARY), 2, 0)
        self._eng_fuel_lbl = _label("---  mA", T.TEXT_PRIMARY, mono=True)
        grid.addWidget(self._eng_fuel_lbl, 2, 1)

        cl.addLayout(grid)
        return container

    def _build_connection_section(self) -> QWidget:
        container, cl = self._section("Connection", T.TEXT_SECONDARY)

        grid = QGridLayout()
        grid.setSpacing(8)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)

        grid.addWidget(_label("Sys ID", T.TEXT_SECONDARY), 0, 0)
        self._conn_sysid = _label("---", T.TEXT_PRIMARY, mono=True)
        grid.addWidget(self._conn_sysid, 0, 1)

        grid.addWidget(_label("HB Sent", T.TEXT_SECONDARY), 0, 2)
        self._conn_hb_sent = _label("0", T.TEXT_PRIMARY, mono=True)
        grid.addWidget(self._conn_hb_sent, 0, 3)

        grid.addWidget(_label("HB Recv", T.TEXT_SECONDARY), 1, 0)
        self._conn_hb_recv = _label("0", T.TEXT_PRIMARY, mono=True)
        grid.addWidget(self._conn_hb_recv, 1, 1)

        grid.addWidget(_label("Last HB", T.TEXT_SECONDARY), 1, 2)
        self._conn_last_hb = _label("---  s", T.TEXT_PRIMARY, mono=True)
        grid.addWidget(self._conn_last_hb, 1, 3)

        cl.addLayout(grid)
        return container

    def _build_message_stream(self) -> QWidget:
        container, cl = self._section("Message Stream  (last 20)", T.PURPLE)

        self._msg_list = QListWidget()
        self._msg_list.setStyleSheet(
            f"QListWidget {{"
            f"  background: {T.BG_BASE};"
            f"  border: 1px solid {T.BORDER};"
            f"  border-radius: 4px;"
            f"  color: {T.TEXT_PRIMARY};"
            f"  font-family: {T.FONT_MONO};"
            f"  font-size: 8pt;"
            f"}}"
            f"QListWidget::item {{"
            f"  padding: 1px 4px;"
            f"  border: none;"
            f"}}"
            f"QListWidget::item:selected {{"
            f"  background: {T.BG_ELEVATED};"
            f"}}"
        )
        self._msg_list.setSpacing(0)
        self._msg_list.setUniformItemSizes(True)
        self._msg_list.setMinimumHeight(140)
        cl.addWidget(self._msg_list)
        return container

    # ── Public update API ─────────────────────────────────────────────────────

    def _show_sections(self) -> None:
        """Hide the not-connected label and reveal all sections."""
        if not self._connected:
            self._connected = True
            self._not_connected_label.hide()
            for sec in self._sections:
                sec.show()

    def update_vehicle_status(self, mode: int, flight_regime: int, armed: bool) -> None:
        """Update vehicle mode, flight regime, and armed state."""
        self._show_sections()
        self._last_mode   = mode
        self._last_armed  = armed
        self._last_regime = flight_regime

        name = get_mode_name(mode)
        colors = {
            ActuationMode.OFF:      (T.BG_ELEVATED, T.TEXT_DISABLED),
            ActuationMode.IBIT:     (T.AMBER_DIM,   T.AMBER),
            ActuationMode.OPERATE:  (T.GREEN_DIM,   T.GREEN),
            ActuationMode.MANUAL:   (T.BLUE_DIM,    T.BLUE),
            ActuationMode.PLAYBACK: (T.PURPLE_DIM,  T.PURPLE),
            ActuationMode.TRIM:     (T.BG_ELEVATED, T.TEXT_SECONDARY),
        }
        bg, fg = colors.get(mode, (T.BG_ELEVATED, T.TEXT_DISABLED))
        self._mode_badge.set_text_color(name, bg, fg)

        regime_str = get_flight_regime_short_name(flight_regime)
        self._regime_label.setText(regime_str or "---")

        if armed:
            self._armed_led.set_state('amber')
            self._armed_label.set_text_color(f"ARMED  {regime_str}", T.AMBER_DIM, T.AMBER)
        else:
            self._armed_led.set_state('green')
            self._armed_label.set_text_color(f"SAFE  {regime_str}", T.GREEN_DIM, T.GREEN)

    def update_relay_state(self, on: bool) -> None:
        """Update relay state LED."""
        if on:
            self._relay_led.set_state('red')
            self._relay_label.set_text_color("ON", T.RED_DIM, T.RED)
        else:
            self._relay_led.set_state('green')
            self._relay_label.set_text_color("OFF", T.GREEN_DIM, T.GREEN)

    def update_actuator_feedback(self, data: dict) -> None:
        """Update all 8 actuator surface rows from a feedback data dict."""
        for key, row in self._actuator_rows.items():
            fb_raw = data.get(f"{key}_feedback_cdeg")
            curr   = data.get(f"{key}_current_mA")
            temp   = data.get(f"{key}_motor_temp_degC")

            fb_deg = fb_raw / 100.0 if fb_raw is not None else None
            row['fb'].setText(f"{fb_deg:.1f}" if fb_deg is not None else "---")
            row['curr'].setText(str(curr) if curr is not None else "---")
            row['temp'].setText(str(temp) if temp is not None else "---")

        # Re-apply mistracking highlights on new data
        self.update_mistracking(self._mistracking_flags)

    def update_ibit_state(self, substate_name: str) -> None:
        """Update the IBIT substate label."""
        color = T.IBIT_PHASE_COLORS.get(substate_name, T.TEXT_SECONDARY)
        self._ibit_substate.setText(substate_name)
        self._ibit_substate.setStyleSheet(
            f"color: {color}; font-family: {T.FONT_MONO}; "
            f"font-weight: bold; font-size: {T.FONT_SIZE_SM}; background: transparent;"
        )

    def update_mistracking(self, flags: int) -> None:
        """Highlight mistracking surfaces.  flags is a bitmask matching actuator_feedback.py."""
        self._mistracking_flags = flags

        # Surface flag labels in IBIT section
        for bit, lbl in self._ibit_surface_labels.items():
            if flags & bit:
                lbl.setStyleSheet(
                    f"color: {T.RED}; font-size: 8pt; font-weight: bold; "
                    f"background: {T.RED_DIM}; border: 1px solid {T.RED}; "
                    f"border-radius: 3px; padding: 1px 3px;"
                )
            else:
                lbl.setStyleSheet(
                    f"color: {T.GREEN}; font-size: 8pt; "
                    f"background: {T.GREEN_DIM}; border: 1px solid {T.GREEN}; "
                    f"border-radius: 3px; padding: 1px 3px;"
                )

        # Actuator table fb cell highlighting
        flag_to_key = {
            64:  "left_elevon",
            128: "right_elevon",
            1:   "dorsal_rudder",
            2:   "ventral_rudder",
            4:   "left_tvc_upper",
            8:   "left_tvc_lower",
            16:  "right_tvc_upper",
            32:  "right_tvc_lower",
        }
        for bit, key in flag_to_key.items():
            row = self._actuator_rows.get(key)
            if not row:
                continue
            fb_lbl = row['fb']
            if flags & bit:
                fb_lbl.setStyleSheet(
                    f"color: {T.RED}; font-weight: bold; font-family: {T.FONT_MONO}; "
                    f"font-size: {T.FONT_SIZE_SM}; background: transparent;"
                )
            else:
                fb_lbl.setStyleSheet(
                    f"color: {T.TEXT_PRIMARY}; font-family: {T.FONT_MONO}; "
                    f"font-size: {T.FONT_SIZE_SM}; background: transparent;"
                )

    def update_battery(self, voltage_mv: int, current_ca: int, soc: int) -> None:
        """Update battery section.  voltage_mv in millivolts, current_ca in centi-amps."""
        voltage_v  = voltage_mv  / 1000.0 if voltage_mv  else 0.0
        current_a  = current_ca  / 100.0  if current_ca  else 0.0
        soc_pct    = max(0, min(100, soc))

        self._batt_voltage_lbl.setText(f"{voltage_v:.2f}  V")
        self._batt_current_lbl.setText(f"{current_a:.1f}  A")
        self._batt_soc_bar.setValue(soc_pct)
        self._batt_soc_lbl.setText(f"{soc_pct}%")

        # Color the SoC bar by charge level
        if soc_pct > 50:
            color = T.GREEN
        elif soc_pct > 20:
            color = T.AMBER
        else:
            color = T.RED
        self._batt_soc_bar.setStyleSheet(
            f"QProgressBar {{ background: {T.BG_BASE}; border: 1px solid {T.BORDER}; "
            f"border-radius: 4px; }}"
            f"QProgressBar::chunk {{ background: {color}; border-radius: 4px; }}"
        )

    def update_engine(self, rpm: int, egt: int, fuel_pump_ma: int) -> None:
        """Update engine telemetry fields."""
        self._eng_rpm_lbl.setText(f"{rpm:,}")
        self._eng_egt_lbl.setText(f"{egt}  °C")
        self._eng_fuel_lbl.setText(f"{fuel_pump_ma}  mA")

    def update_connection(self, sysid: int, hb_sent: int, hb_recv: int, last_hb_s: float) -> None:
        """Update connection health fields."""
        self._conn_sysid.setText(str(sysid) if sysid else "---")
        self._conn_hb_sent.setText(str(hb_sent))
        self._conn_hb_recv.setText(str(hb_recv))

        if last_hb_s >= 0:
            color = T.GREEN if last_hb_s < 3 else (T.AMBER if last_hb_s < 10 else T.RED)
            self._conn_last_hb.setText(f"{last_hb_s:.1f}  s")
            self._conn_last_hb.setStyleSheet(
                f"color: {color}; font-family: {T.FONT_MONO}; "
                f"font-size: {T.FONT_SIZE_SM}; background: transparent;"
            )
        else:
            self._conn_last_hb.setText("---  s")

    def add_message(self, msg_type: str, summary: str) -> None:
        """Append a message to the rolling stream list (capped at _MSG_MAX)."""
        ts    = datetime.now().strftime('%H:%M:%S.%f')[:-4]
        color = _MSG_TYPE_COLORS.get(msg_type.upper(), T.TEXT_SECONDARY)
        text  = f"[{ts}] {msg_type:<36}  {summary}"

        item = QListWidgetItem(text)
        item.setForeground(__import__('PyQt5.QtGui', fromlist=['QColor']).QColor(color))
        self._msg_list.addItem(item)

        # Keep only the last _MSG_MAX entries
        while self._msg_list.count() > _MSG_MAX:
            self._msg_list.takeItem(0)

        # Auto-scroll to bottom
        self._msg_list.scrollToBottom()

    def reset(self) -> None:
        """Reset all telemetry fields to their default/idle state."""
        self._mistracking_flags = 0
        self._last_mode   = 0
        self._last_armed  = False
        self._last_regime = 0
        self._connected   = False

        # Show "not connected" overlay, hide all sections
        self._not_connected_label.show()
        for sec in self._sections:
            sec.hide()

        # Vehicle status
        self._mode_badge.set_text_color("---", T.BG_ELEVATED, T.TEXT_DISABLED)
        self._regime_label.setText("---")
        self._armed_led.set_state(None)
        self._armed_label.set_text_color("DISARMED", T.GREEN_DIM, T.GREEN)
        self._relay_led.set_state(None)
        self._relay_label.set_text_color("UNKNOWN", T.BG_ELEVATED, T.TEXT_DISABLED)

        # IBIT
        self._ibit_substate.setText("IDLE")
        self._ibit_substate.setStyleSheet(
            f"color: {T.TEXT_DISABLED}; font-family: {T.FONT_MONO}; "
            f"font-weight: bold; font-size: {T.FONT_SIZE_SM}; background: transparent;"
        )
        for lbl in self._ibit_surface_labels.values():
            lbl.setStyleSheet(
                f"color: {T.TEXT_DISABLED}; font-size: 8pt; "
                f"background: {T.BG_BASE}; border: 1px solid {T.BORDER}; "
                f"border-radius: 3px; padding: 1px 3px;"
            )

        # Actuator table
        for row in self._actuator_rows.values():
            row['fb'].setText("---")
            row['curr'].setText("---")
            row['temp'].setText("---")
            row['fb'].setStyleSheet(
                f"color: {T.TEXT_PRIMARY}; font-family: {T.FONT_MONO}; "
                f"font-size: {T.FONT_SIZE_SM}; background: transparent;"
            )

        # Battery
        self._batt_voltage_lbl.setText("---  V")
        self._batt_current_lbl.setText("---  A")
        self._batt_soc_bar.setValue(0)
        self._batt_soc_lbl.setText("---%")

        # Engine
        self._eng_rpm_lbl.setText("---")
        self._eng_egt_lbl.setText("---  °C")
        self._eng_fuel_lbl.setText("---  mA")

        # Connection
        self._conn_sysid.setText("---")
        self._conn_hb_sent.setText("0")
        self._conn_hb_recv.setText("0")
        self._conn_last_hb.setText("---  s")

        # Message stream
        self._msg_list.clear()
