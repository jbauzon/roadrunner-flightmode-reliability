"""IBIT / Playback test status display widget."""
from __future__ import annotations

from PyQt5.QtWidgets import QGroupBox, QVBoxLayout, QHBoxLayout, QWidget, QLabel, QProgressBar, QFrame
from PyQt5.QtCore import Qt

from .. import theme as T
from .primitives import StatusBadge, _label
from vehicle.constants import TestMode


class IBITDisplayWidget(QGroupBox):
    """Test status display — adapts between IBIT substate tracking and playback streaming."""

    _IBIT_PHASES = ["BEGIN", "WAIT_FOR_SETTLE", "ELEVONS", "RUDDERS", "TVC"]

    def __init__(self, parent=None):
        super().__init__("Test Status", parent)
        self._mode = 'ibit'
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 16, 12, 12)
        layout.setSpacing(10)

        # ── Primary state badge ───────────────────────────────────────────
        self.state_badge = QLabel("IDLE")
        self.state_badge.setAlignment(Qt.AlignCenter)
        self.state_badge.setFixedHeight(48)
        self.state_badge.setStyleSheet(
            f"background-color: {T.BG_ELEVATED}; color: {T.TEXT_DISABLED}; "
            f"border-radius: 8px; font-family: {T.FONT_MONO}; "
            f"font-size: {T.FONT_SIZE_XL}; font-weight: bold; letter-spacing: 2px;"
        )
        layout.addWidget(self.state_badge)

        # ── IBIT phase stepper ────────────────────────────────────────────
        self._phase_container = QWidget()
        phase_row = QHBoxLayout(self._phase_container)
        phase_row.setContentsMargins(0, 0, 0, 0)
        phase_row.setSpacing(4)
        self._phase_dots = []
        for name in self._IBIT_PHASES:
            dot = QWidget()
            dot.setFixedSize(12, 12)
            dot.setStyleSheet(f"background-color: {T.BG_ELEVATED}; border-radius: 6px; border: 1px solid {T.BORDER};")
            dot.setToolTip(name)
            self._phase_dots.append(dot)
            phase_row.addWidget(dot)
            if name != self._IBIT_PHASES[-1]:
                line = QFrame()
                line.setFrameShape(QFrame.HLine)
                line.setStyleSheet(f"background: {T.BORDER}; max-height: 1px; min-width: 12px;")
                phase_row.addWidget(line, 1)
        phase_row.addStretch()
        layout.addWidget(self._phase_container)

        # ── Playback progress bar ─────────────────────────────────────────
        self._playback_container = QWidget()
        pb_layout = QVBoxLayout(self._playback_container)
        pb_layout.setContentsMargins(0, 0, 0, 0)
        pb_layout.setSpacing(4)
        self.playback_pct_label = _label("0%", T.PURPLE, bold=True, mono=True, size=T.FONT_SIZE_LG)
        pb_layout.addWidget(self.playback_pct_label)
        self.playback_bar = QProgressBar()
        self.playback_bar.setRange(0, 100)
        self.playback_bar.setValue(0)
        self.playback_bar.setFixedHeight(10)
        self.playback_bar.setStyleSheet(
            f"QProgressBar {{ background: {T.BG_ELEVATED}; border-radius: 5px; border: none; }}"
            f"QProgressBar::chunk {{ background: {T.PURPLE}; border-radius: 5px; }}"
        )
        pb_layout.addWidget(self.playback_bar)
        self._playback_container.setVisible(False)
        layout.addWidget(self._playback_container)

        # ── Mistracking (playback) ────────────────────────────────────────
        self._mistracking_container = QWidget()
        mt_layout = QHBoxLayout(self._mistracking_container)
        mt_layout.setContentsMargins(0, 0, 0, 0)
        mt_layout.setSpacing(6)
        mt_layout.addWidget(_label("Mistracking:", T.TEXT_SECONDARY))
        self.mistracking_badge = StatusBadge("NONE")
        self.mistracking_badge.set_color(T.GREEN_DIM, T.GREEN)
        mt_layout.addWidget(self.mistracking_badge)
        mt_layout.addStretch()
        self._mistracking_container.setVisible(False)
        layout.addWidget(self._mistracking_container)

        # ── Duration ─────────────────────────────────────────────────────
        dur_row = QHBoxLayout()
        dur_row.addWidget(_label("Duration:", T.TEXT_SECONDARY))
        self.duration_label = _label("0.0 s", mono=True)
        dur_row.addWidget(self.duration_label)
        dur_row.addStretch()
        layout.addLayout(dur_row)

        # Hint
        self.hint_label = _label(
            "Phases: BEGIN \u2192 SETTLE \u2192 ELEVONS \u2192 RUDDERS \u2192 TVC",
            T.TEXT_SECONDARY, size=T.FONT_SIZE
        )
        layout.addWidget(self.hint_label)

    # ── Public API ───────────────────────────────────────────────────────

    def set_mode(self, mode):
        self._mode = mode
        is_pb = (mode == TestMode.PLAYBACK)
        self._phase_container.setVisible(not is_pb)
        self._playback_container.setVisible(is_pb)
        self._mistracking_container.setVisible(is_pb)
        self.hint_label.setText(
            "Streaming 100 Hz flight profile \u2014 real-time surface tracking"
            if is_pb else
            "Phases: BEGIN \u2192 SETTLE \u2192 ELEVONS \u2192 RUDDERS \u2192 TVC"
        )
        self.reset()

    def set_substate(self, substate_name):
        """Update the IBIT phase display for the given substate name."""
        color = T.IBIT_PHASE_COLORS.get(substate_name, T.TEXT_DISABLED)
        bg_map = {
            T.GREEN: T.GREEN_DIM,
            T.AMBER: T.AMBER_DIM,
            T.BLUE:  T.BLUE_DIM,
            T.RED:   T.RED_DIM,
        }
        bg = bg_map.get(color, T.BG_ELEVATED)
        self.state_badge.setText(substate_name)
        self.state_badge.setStyleSheet(
            f"background-color: {bg}; color: {color}; "
            f"border-radius: 8px; font-family: {T.FONT_MONO}; "
            f"font-size: {T.FONT_SIZE_XL}; font-weight: bold; letter-spacing: 2px; "
            f"border: 1px solid {color};"
        )
        # Update phase dots
        phase_map = {
            "BEGIN": 0, "WAIT_FOR_SETTLE": 1, "ELEVONS": 2, "RUDDERS": 3, "TVC": 4
        }
        current_idx = phase_map.get(substate_name, -1)
        for i, dot in enumerate(self._phase_dots):
            if i < current_idx:
                dot.setStyleSheet(f"background-color: {T.GREEN}; border-radius: 6px;")
            elif i == current_idx:
                dot.setStyleSheet(f"background-color: {T.AMBER}; border-radius: 6px;")
            else:
                dot.setStyleSheet(f"background-color: {T.BG_ELEVATED}; border-radius: 6px; border: 1px solid {T.BORDER};")
        if substate_name == "\u2713 COMPLETE":
            for dot in self._phase_dots:
                dot.setStyleSheet(f"background-color: {T.GREEN}; border-radius: 6px;")

    def set_playback_progress(self, percent):
        """Update playback progress bar and percentage label."""
        self.playback_pct_label.setText(f"{percent}%")
        self.playback_bar.setValue(percent)
        color = T.GREEN if percent >= 100 else (T.PURPLE if percent >= 50 else T.BLUE)
        self.state_badge.setText(f"STREAMING  {percent}%")
        self.state_badge.setStyleSheet(
            f"background-color: {T.PURPLE_DIM}; color: {color}; "
            f"border-radius: 8px; font-family: {T.FONT_MONO}; "
            f"font-size: {T.FONT_SIZE_XL}; font-weight: bold; letter-spacing: 2px; "
            f"border: 1px solid {color};"
        )

    def set_mistracking(self, flags, flag_names):
        if flags == 0:
            self.mistracking_badge.set_text_color("NONE", T.GREEN_DIM, T.GREEN)
        else:
            self.mistracking_badge.set_text_color(
                ", ".join(flag_names), T.RED_DIM, T.RED
            )

    def set_duration(self, duration):
        """Update the test duration display (in seconds)."""
        m, s = divmod(int(duration), 60)
        self.duration_label.setText(f"{m:02d}:{s:02d}  ({duration:.1f}s)")

    def reset(self):
        """Reset display to idle state."""
        self.state_badge.setText("IDLE")
        self.state_badge.setStyleSheet(
            f"background-color: {T.BG_ELEVATED}; color: {T.TEXT_DISABLED}; "
            f"border-radius: 8px; font-family: {T.FONT_MONO}; "
            f"font-size: {T.FONT_SIZE_XL}; font-weight: bold; letter-spacing: 2px;"
        )
        for dot in self._phase_dots:
            dot.setStyleSheet(f"background-color: {T.BG_ELEVATED}; border-radius: 6px; border: 1px solid {T.BORDER};")
        self.playback_bar.setValue(0)
        self.playback_pct_label.setText("0%")
        self.duration_label.setText("00:00  (0.0s)")
        self.mistracking_badge.set_text_color("NONE", T.GREEN_DIM, T.GREEN)
