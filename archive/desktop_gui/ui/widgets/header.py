"""Header banner with app title, mode pill, and live clock."""
from __future__ import annotations

from PyQt5.QtWidgets import QWidget, QHBoxLayout, QLabel, QSizePolicy
from PyQt5.QtCore import QTimer
from datetime import datetime

from .. import theme as T
from .primitives import StatusBadge
from rr_test.vehicle.constants import TestMode


class HeaderBanner(QWidget):
    """Top bar with app title, mode pill and live clock."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"background-color: {T.BG_ELEVATED}; "
            f"border-bottom: 2px solid {T.BORDER};"
        )
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(56)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 0, 20, 0)

        # Logo / title
        title = QLabel("ROADRUNNER  FLIGHT TEST")
        title.setStyleSheet(
            f"color: {T.TEXT_PRIMARY}; font-size: 15pt; font-weight: bold; "
            f"letter-spacing: 2px; background: transparent;"
        )
        layout.addWidget(title)

        layout.addStretch()

        # Mode pill
        self.mode_badge = StatusBadge("IBIT MODE")
        self.mode_badge.setFixedWidth(180)
        self.mode_badge.set_color(T.BLUE_DIM, T.BLUE)
        layout.addWidget(self.mode_badge)

        layout.addSpacing(20)

        # Clock
        self.clock_label = QLabel()
        self.clock_label.setStyleSheet(
            f"color: {T.TEXT_SECONDARY}; font-family: {T.FONT_MONO}; "
            f"font-size: {T.FONT_SIZE_SM}; background: transparent;"
        )
        layout.addWidget(self.clock_label)

        self._clock_timer = QTimer()
        self._clock_timer.timeout.connect(self._tick)
        self._clock_timer.start(1000)
        self._tick()

    def _tick(self):
        self.clock_label.setText(datetime.now().strftime("%Y-%m-%d  %H:%M:%S"))

    def set_mode(self, mode):
        if mode == TestMode.PLAYBACK:
            self.mode_badge.setText("PLAYBACK MODE")
            self.mode_badge.set_color(T.PURPLE_DIM, T.PURPLE)
        else:
            self.mode_badge.setText("IBIT MODE")
            self.mode_badge.set_color(T.BLUE_DIM, T.BLUE)
