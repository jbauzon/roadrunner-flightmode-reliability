"""Primitive helpers and small indicator widgets."""
from __future__ import annotations

from PyQt5.QtWidgets import QLabel, QFrame
from PyQt5.QtCore import Qt

from .. import theme as T


# ── Helpers ────────────────────────────────────────────────────────────────────

def _sep():
    """Horizontal rule separator."""
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setStyleSheet(f"color: {T.BORDER}; background-color: {T.BORDER}; border: none; max-height: 1px;")
    return line


def _label(text, color=None, bold=False, mono=False, size=None):
    lbl = QLabel(text)
    style = f"background: transparent; color: {color or T.TEXT_PRIMARY};"
    if bold:
        style += " font-weight: bold;"
    if mono:
        style += f" font-family: {T.FONT_MONO};"
    if size:
        style += f" font-size: {size};"
    lbl.setStyleSheet(style)
    return lbl


def _section_title(text):
    lbl = QLabel(text.upper())
    lbl.setStyleSheet(
        f"color: {T.TEXT_SECONDARY}; font-size: {T.FONT_SIZE_SM}; "
        f"font-weight: bold; letter-spacing: 1px; background: transparent;"
    )
    return lbl


# ── StatusBadge ────────────────────────────────────────────────────────────────

class StatusBadge(QLabel):
    """Pill badge — text + background color."""

    def __init__(self, text="---", parent=None):
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignCenter)
        self.set_color(T.BG_ELEVATED)

    def set_color(self, bg, text=T.WHITE):
        """Set badge background and text colors."""
        self.setStyleSheet(T.badge_style(bg, text))

    def set_text_color(self, text, bg, fg=T.WHITE):
        """Set text content and colors."""
        self.setText(text)
        self.set_color(bg, fg)


# ── LED ────────────────────────────────────────────────────────────────────────

class LED(QLabel):
    """Single dot LED indicator."""

    def __init__(self, parent=None):
        super().__init__("●", parent)
        self.setAlignment(Qt.AlignCenter)
        self.set_state(None)

    def set_state(self, state):
        """Set LED state: 'green', 'red', 'amber', 'blue', or None (grey)."""
        colors = {
            'green': T.GREEN,
            'red':   T.RED,
            'amber': T.AMBER,
            'blue':  T.BLUE,
            None:    T.TEXT_DISABLED,
        }
        self.setStyleSheet(T.led_style(colors.get(state, T.TEXT_DISABLED)))
