"""Vehicle status panel — link, armed, mode indicators."""
from __future__ import annotations

from PyQt5.QtWidgets import QGroupBox, QGridLayout

from .. import theme as T
from .primitives import StatusBadge, LED, _label
from vehicle.constants import ActuationMode, get_mode_name, get_flight_regime_short_name


class StatusPanelWidget(QGroupBox):
    def __init__(self, parent=None):
        super().__init__("Vehicle Status", parent)
        self._init_ui()

    def _init_ui(self):
        layout = QGridLayout(self)
        layout.setContentsMargins(12, 16, 12, 12)
        layout.setSpacing(10)
        layout.setColumnStretch(2, 1)

        # Connection
        layout.addWidget(_label("Link", T.TEXT_SECONDARY), 0, 0)
        self.connection_led   = LED()
        self.connection_label = StatusBadge("OFFLINE")
        self.connection_label.set_color(T.BG_ELEVATED, T.TEXT_DISABLED)
        layout.addWidget(self.connection_led,   0, 1)
        layout.addWidget(self.connection_label, 0, 2)

        # Armed
        layout.addWidget(_label("Armed", T.TEXT_SECONDARY), 1, 0)
        self.armed_led   = LED()
        self.armed_label = StatusBadge("DISARMED")
        self.armed_label.set_color(T.GREEN_DIM, T.GREEN)
        layout.addWidget(self.armed_led,   1, 1)
        layout.addWidget(self.armed_label, 1, 2)

        # Mode
        layout.addWidget(_label("Mode", T.TEXT_SECONDARY), 2, 0)
        self.mode_badge = StatusBadge("---")
        self.mode_badge.set_color(T.BG_ELEVATED, T.TEXT_DISABLED)
        layout.addWidget(self.mode_badge, 2, 1, 1, 2)

    def set_connection_health(self, is_healthy):
        """Update the connection LED and label."""
        if is_healthy:
            self.connection_led.set_state('green')
            self.connection_label.set_text_color("CONNECTED", T.GREEN_DIM, T.GREEN)
        else:
            self.connection_led.set_state('red')
            self.connection_label.set_text_color("LINK LOST", T.RED_DIM, T.RED)

    def set_armed_state(self, armed, flight_regime):
        """Update the armed state LED and label."""
        regime_str = get_flight_regime_short_name(flight_regime)
        if armed:
            self.armed_led.set_state('amber')
            self.armed_label.set_text_color(f"ARMED  {regime_str}", T.AMBER_DIM, T.AMBER)
        else:
            self.armed_led.set_state('green')
            self.armed_label.set_text_color(f"SAFE  {regime_str}", T.GREEN_DIM, T.GREEN)

    def set_mode(self, mode):
        """Update the actuation mode badge."""
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
        self.mode_badge.set_text_color(name, bg, fg)

    def reset(self):
        """Reset all indicators to idle/offline state."""
        self.connection_led.set_state(None)
        self.connection_label.set_text_color("OFFLINE", T.BG_ELEVATED, T.TEXT_DISABLED)
        self.armed_led.set_state(None)
        self.armed_label.set_text_color("DISARMED", T.GREEN_DIM, T.GREEN)
        self.mode_badge.set_text_color("---", T.BG_ELEVATED, T.TEXT_DISABLED)
