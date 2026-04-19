"""Batch progress widget — testing, iteration, elapsed, remaining, progress bar."""
from __future__ import annotations

import time

from PyQt5.QtWidgets import QGroupBox, QGridLayout, QProgressBar

from .. import theme as T
from .primitives import _label
from rr_test.vehicle.constants import TestMode


class ProgressWidget(QGroupBox):
    def __init__(self, parent=None):
        super().__init__("Batch Progress", parent)
        self._init_ui()

    def _init_ui(self):
        layout = QGridLayout(self)
        layout.setContentsMargins(12, 16, 12, 12)
        layout.setSpacing(10)
        layout.setColumnStretch(1, 1)
        layout.setColumnStretch(3, 1)

        # Row 0
        layout.addWidget(_label("Testing:", T.TEXT_SECONDARY), 0, 0)
        self.current_uut_label = _label("---", bold=True)
        layout.addWidget(self.current_uut_label, 0, 1)

        layout.addWidget(_label("Elapsed:", T.TEXT_SECONDARY), 0, 2)
        self.elapsed_label = _label("00:00:00", mono=True)
        layout.addWidget(self.elapsed_label, 0, 3)

        # Row 1
        self._iteration_title_label = _label("Iteration:", T.TEXT_SECONDARY)
        layout.addWidget(self._iteration_title_label, 1, 0)
        self.iteration_label = _label("0", bold=True, mono=True)
        layout.addWidget(self.iteration_label, 1, 1)

        layout.addWidget(_label("Remaining:", T.TEXT_SECONDARY), 1, 2)
        self.remaining_label = _label("00:00:00", mono=True)
        layout.addWidget(self.remaining_label, 1, 3)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setTextVisible(False)
        layout.addWidget(self.progress_bar, 2, 0, 1, 4)

    def set_current_uut(self, text):
        """Set the current UUT label text."""
        self.current_uut_label.setText(text)

    def set_test_mode(self, mode):
        """Set iteration/frame label based on test mode."""
        self._iteration_title_label.setText(
            "Iteration:" if mode == TestMode.IBIT else "Frame:"
        )

    def set_iteration(self, iteration):
        """Set the iteration counter."""
        self.iteration_label.setText(str(iteration))

    def set_elapsed(self, seconds):
        """Set elapsed time display."""
        self.elapsed_label.setText(time.strftime('%H:%M:%S', time.gmtime(seconds)))

    def set_remaining(self, seconds):
        """Set remaining time display."""
        self.remaining_label.setText(time.strftime('%H:%M:%S', time.gmtime(seconds)))

    def set_progress(self, percent):
        """Set the progress bar percentage."""
        self.progress_bar.setValue(percent)
