"""Auto-hide alert banner widget."""
from __future__ import annotations

from PyQt5.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton
from PyQt5.QtCore import QTimer

from .. import theme as T


class AlertBannerWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setVisible(False)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 8)

        self._icon = QLabel("\u26a0")
        self._icon.setStyleSheet(
            f"color: {T.AMBER}; font-size: 16pt; background: transparent;"
        )
        layout.addWidget(self._icon)

        self._label = QLabel()
        self._label.setStyleSheet(
            f"color: {T.WHITE}; font-size: {T.FONT_SIZE}; font-weight: bold; "
            f"background: transparent;"
        )
        self._label.setWordWrap(True)
        layout.addWidget(self._label, 1)

        self._dismiss = QPushButton("\u2715")
        self._dismiss.setFixedSize(24, 24)
        self._dismiss.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {T.TEXT_SECONDARY}; "
            f"border: none; font-size: 12pt; }}"
            f"QPushButton:hover {{ color: {T.WHITE}; }}"
        )
        self._dismiss.clicked.connect(self.hide)
        layout.addWidget(self._dismiss)

        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def show_alert(self, message, severity='warning', auto_hide_ms=10000):
        """Display an alert banner with the given message and severity."""
        colors = {
            'warning':  (T.AMBER_DIM, T.AMBER,  T.AMBER,  "\u26a0"),
            'error':    (T.RED_DIM,   T.RED,    T.RED,    "\u2717"),
            'critical': (T.RED,       T.WHITE,  T.WHITE,  "\u26a0\u26a0\u26a0"),
            'info':     (T.BLUE_DIM,  T.BLUE,   T.BLUE,   "\u2139"),
        }
        bg, border, icon_color, icon = colors.get(severity, colors['warning'])
        self.setStyleSheet(
            f"background-color: {bg}; border-left: 4px solid {border}; "
            f"border-radius: 6px;"
        )
        self._icon.setText(icon)
        self._icon.setStyleSheet(f"color: {icon_color}; font-size: 16pt; background: transparent;")
        self._label.setText(message)
        self.setVisible(True)
        if auto_hide_ms > 0:
            self._timer.start(auto_hide_ms)
