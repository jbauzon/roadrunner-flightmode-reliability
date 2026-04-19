"""Start/stop/emergency control buttons."""
from __future__ import annotations

from PyQt5.QtWidgets import QWidget, QHBoxLayout, QPushButton
from PyQt5.QtCore import pyqtSignal

from .. import theme as T
from vehicle.constants import TestMode


class ControlButtonsWidget(QWidget):
    start_clicked     = pyqtSignal()
    stop_clicked      = pyqtSignal()
    emergency_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.start_btn = QPushButton("\u25b6  Start IBIT Test")
        self.start_btn.setStyleSheet(T.btn_primary())
        self.start_btn.setMinimumHeight(48)
        self.start_btn.clicked.connect(self.start_clicked)
        layout.addWidget(self.start_btn, 2)

        self.stop_btn = QPushButton("\u23f9  Stop")
        self.stop_btn.setStyleSheet(T.btn_danger())
        self.stop_btn.setMinimumHeight(48)
        self.stop_btn.setMinimumWidth(120)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_clicked)
        layout.addWidget(self.stop_btn, 1)

        self.emergency_btn = QPushButton("\u26a1  EMERGENCY STOP")
        self.emergency_btn.setStyleSheet(T.btn_emergency())
        self.emergency_btn.setMinimumHeight(48)
        self.emergency_btn.clicked.connect(self.emergency_clicked)
        layout.addWidget(self.emergency_btn, 1)

    def set_testing_mode(self, testing):
        """Enable/disable buttons for testing state."""
        self.start_btn.setEnabled(not testing)
        self.stop_btn.setEnabled(testing)

    def set_test_mode_label(self, mode):
        """Update the start button label for the current test mode."""
        if mode == TestMode.PLAYBACK:
            self.start_btn.setText("\u25b6  Start Playback Test")
        else:
            self.start_btn.setText("\u25b6  Start IBIT Test")

    def set_enabled(self, start_enabled, stop_enabled):
        """Explicitly set button enabled states."""
        self.start_btn.setEnabled(start_enabled)
        self.stop_btn.setEnabled(stop_enabled)
