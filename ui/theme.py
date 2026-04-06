"""
Theme - Dark professional operator console stylesheet.

Anduril-style dark theme designed for sustained readability in a
manufacturing/test environment. All colors, fonts and spacing
are defined here so the entire UI can be re-skinned from one file.
"""

# ── Palette ──────────────────────────────────────────────────────────────────
BG_BASE       = "#0D1117"   # Window / deepest background
BG_SURFACE    = "#161B22"   # Cards, group boxes
BG_ELEVATED   = "#21262D"   # Inputs, table rows
BG_HOVER      = "#30363D"   # Hover states
BORDER        = "#30363D"   # Subtle borders
BORDER_FOCUS  = "#58A6FF"   # Focused input border

TEXT_PRIMARY   = "#E6EDF3"  # Main text
TEXT_SECONDARY = "#8B949E"  # Muted / labels
TEXT_DISABLED  = "#484F58"  # Disabled

# Status / semantic
GREEN         = "#3FB950"   # Pass, connected, armed OK
GREEN_DIM     = "#1A3D22"   # Green background
AMBER         = "#D29922"   # Warning
AMBER_DIM     = "#3D2F0A"
RED           = "#F85149"   # Fail, error, emergency
RED_DIM       = "#3D1212"
BLUE          = "#58A6FF"   # Info, active, selected
BLUE_DIM      = "#0C2A4A"
PURPLE        = "#BC8CFF"   # Playback mode
PURPLE_DIM    = "#2A1A3D"
TEAL          = "#39D353"   # IBIT COMPLETE
ORANGE        = "#E3B341"   # OPERATE mode
WHITE         = "#FFFFFF"

# Button accents
BTN_PRIMARY_BG   = "#238636"
BTN_PRIMARY_HOVER= "#2EA043"
BTN_DANGER_BG    = "#DA3633"
BTN_DANGER_HOVER = "#F85149"
BTN_EMRG_BG      = "#B91C1C"
BTN_EMRG_HOVER   = "#DC2626"
BTN_NEUTRAL_BG   = "#21262D"
BTN_NEUTRAL_HOVER= "#30363D"

FONT_FAMILY  = "Segoe UI, Arial, sans-serif"
FONT_MONO    = "Consolas, Courier New, monospace"
FONT_SIZE    = "10pt"
FONT_SIZE_SM = "9pt"
FONT_SIZE_LG = "12pt"
FONT_SIZE_XL = "14pt"


def apply(app):
    """Apply the dark theme to a QApplication instance."""
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)


STYLESHEET = f"""
/* ── Base ───────────────────────────────────────────────────────────── */
QWidget {{
    background-color: {BG_BASE};
    color: {TEXT_PRIMARY};
    font-family: {FONT_FAMILY};
    font-size: {FONT_SIZE};
}}

QMainWindow {{
    background-color: {BG_BASE};
}}

/* ── Group Boxes ────────────────────────────────────────────────────── */
QGroupBox {{
    background-color: {BG_SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
    margin-top: 14px;
    padding: 10px 8px 8px 8px;
    font-weight: bold;
    font-size: {FONT_SIZE};
    color: {TEXT_SECONDARY};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 8px;
    left: 12px;
    color: {TEXT_SECONDARY};
    font-size: {FONT_SIZE_SM};
    letter-spacing: 0.5px;
    text-transform: uppercase;
}}

/* ── Labels ─────────────────────────────────────────────────────────── */
QLabel {{
    background: transparent;
    color: {TEXT_PRIMARY};
    font-size: {FONT_SIZE};
}}

/* ── Inputs ─────────────────────────────────────────────────────────── */
QLineEdit, QSpinBox, QComboBox {{
    background-color: {BG_ELEVATED};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 5px 8px;
    color: {TEXT_PRIMARY};
    font-size: {FONT_SIZE};
    min-height: 28px;
    selection-background-color: {BLUE_DIM};
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{
    border: 1px solid {BORDER_FOCUS};
}}
QLineEdit:read-only {{
    color: {TEXT_SECONDARY};
    background-color: {BG_BASE};
}}
QSpinBox::up-button, QSpinBox::down-button {{
    background-color: {BG_HOVER};
    border: none;
    width: 18px;
    border-radius: 3px;
}}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
    background-color: {BORDER_FOCUS};
}}

/* ── Combo ──────────────────────────────────────────────────────────── */
QComboBox::drop-down {{
    border: none;
    width: 24px;
}}
QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 6px solid {TEXT_SECONDARY};
    width: 0;
    height: 0;
}}
QComboBox QAbstractItemView {{
    background-color: {BG_ELEVATED};
    border: 1px solid {BORDER};
    color: {TEXT_PRIMARY};
    selection-background-color: {BLUE_DIM};
    outline: none;
}}

/* ── Checkboxes & Radios ────────────────────────────────────────────── */
QCheckBox, QRadioButton {{
    color: {TEXT_PRIMARY};
    spacing: 8px;
    background: transparent;
}}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    border: 2px solid {BORDER};
    border-radius: 3px;
    background-color: {BG_ELEVATED};
}}
QRadioButton::indicator {{
    border-radius: 8px;
}}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background-color: {BLUE};
    border-color: {BLUE};
}}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
    border-color: {BORDER_FOCUS};
}}

/* ── Buttons ────────────────────────────────────────────────────────── */
QPushButton {{
    background-color: {BTN_NEUTRAL_BG};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 14px;
    font-size: {FONT_SIZE};
    min-height: 28px;
}}
QPushButton:hover {{
    background-color: {BTN_NEUTRAL_HOVER};
    border-color: {TEXT_SECONDARY};
}}
QPushButton:pressed {{
    background-color: {BG_BASE};
}}
QPushButton:disabled {{
    color: {TEXT_DISABLED};
    border-color: {TEXT_DISABLED};
    background-color: {BG_BASE};
}}

/* ── Table ──────────────────────────────────────────────────────────── */
QTableWidget {{
    background-color: {BG_SURFACE};
    border: 1px solid {BORDER};
    border-radius: 6px;
    gridline-color: {BORDER};
    color: {TEXT_PRIMARY};
    selection-background-color: {BLUE_DIM};
    outline: none;
}}
QTableWidget::item {{
    padding: 6px 10px;
    border: none;
}}
QTableWidget::item:selected {{
    background-color: {BLUE_DIM};
    color: {TEXT_PRIMARY};
}}
QHeaderView::section {{
    background-color: {BG_ELEVATED};
    color: {TEXT_SECONDARY};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 6px 10px;
    font-size: {FONT_SIZE_SM};
    font-weight: bold;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}}

/* ── Progress Bar ───────────────────────────────────────────────────── */
QProgressBar {{
    background-color: {BG_ELEVATED};
    border: 1px solid {BORDER};
    border-radius: 4px;
    height: 8px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{
    background-color: {BLUE};
    border-radius: 4px;
}}

/* ── Text Edit (Log) ────────────────────────────────────────────────── */
QTextEdit {{
    background-color: {BG_BASE};
    border: 1px solid {BORDER};
    border-radius: 6px;
    color: {GREEN};
    font-family: {FONT_MONO};
    font-size: {FONT_SIZE_SM};
    padding: 6px;
    selection-background-color: {BLUE_DIM};
}}

/* ── Scroll Bars ────────────────────────────────────────────────────── */
QScrollBar:vertical {{
    background: {BG_BASE};
    width: 8px;
    border-radius: 4px;
}}
QScrollBar::handle:vertical {{
    background: {BORDER};
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: {TEXT_SECONDARY};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: {BG_BASE};
    height: 8px;
}}
QScrollBar::handle:horizontal {{
    background: {BORDER};
    border-radius: 4px;
    min-width: 30px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

/* ── Dialogs ────────────────────────────────────────────────────────── */
QDialog {{
    background-color: {BG_SURFACE};
}}
QDialogButtonBox QPushButton {{
    min-width: 80px;
}}

/* ── Tooltip ────────────────────────────────────────────────────────── */
QToolTip {{
    background-color: {BG_ELEVATED};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 4px 8px;
    font-size: {FONT_SIZE_SM};
}}

/* ── Status Bar ─────────────────────────────────────────────────────── */
QStatusBar {{
    background-color: {BG_ELEVATED};
    color: {TEXT_SECONDARY};
    border-top: 1px solid {BORDER};
    font-size: {FONT_SIZE_SM};
    padding: 0 8px;
}}
"""


# ── Specific widget helpers ───────────────────────────────────────────────────

def card_style(border_color=None):
    """Style for a flat card panel."""
    bc = border_color or BORDER
    return (
        f"background-color: {BG_SURFACE}; "
        f"border: 1px solid {bc}; "
        f"border-radius: 8px; "
        f"padding: 10px;"
    )


def badge_style(bg, text=WHITE, bold=True):
    """Pill-shaped badge."""
    fw = "bold" if bold else "normal"
    return (
        f"background-color: {bg}; color: {text}; "
        f"border-radius: 4px; padding: 3px 10px; "
        f"font-weight: {fw}; font-family: {FONT_MONO}; "
        f"font-size: {FONT_SIZE_SM};"
    )


def led_style(color):
    """Circular LED indicator."""
    return (
        f"color: {color}; font-size: 18pt; "
        f"background: transparent;"
    )


def btn_primary():
    return (
        f"QPushButton {{ background-color: {BTN_PRIMARY_BG}; color: {WHITE}; "
        f"border: none; border-radius: 6px; padding: 8px 20px; "
        f"font-weight: bold; font-size: {FONT_SIZE}; min-height: 36px; }}"
        f"QPushButton:hover {{ background-color: {BTN_PRIMARY_HOVER}; }}"
        f"QPushButton:disabled {{ background-color: {BG_ELEVATED}; "
        f"color: {TEXT_DISABLED}; }}"
    )


def btn_danger():
    return (
        f"QPushButton {{ background-color: {BTN_DANGER_BG}; color: {WHITE}; "
        f"border: none; border-radius: 6px; padding: 8px 20px; "
        f"font-weight: bold; font-size: {FONT_SIZE}; min-height: 36px; }}"
        f"QPushButton:hover {{ background-color: {BTN_DANGER_HOVER}; }}"
        f"QPushButton:disabled {{ background-color: {BG_ELEVATED}; "
        f"color: {TEXT_DISABLED}; }}"
    )


def btn_emergency():
    return (
        f"QPushButton {{ background-color: {BTN_EMRG_BG}; color: {WHITE}; "
        f"border: 2px solid {RED}; border-radius: 6px; padding: 8px 20px; "
        f"font-weight: bold; font-size: {FONT_SIZE_LG}; min-height: 56px; "
        f"letter-spacing: 1px; }}"
        f"QPushButton:hover {{ background-color: {BTN_EMRG_HOVER}; "
        f"border-color: {WHITE}; }}"
    )


MODE_COLORS = {
    'OFF':      BG_ELEVATED,
    'IBIT':     AMBER,
    'OPERATE':  GREEN,
    'MANUAL':   BLUE,
    'PLAYBACK': PURPLE,
    'TRIM':     TEAL,
    'UNKNOWN':  TEXT_DISABLED,
}

IBIT_PHASE_COLORS = {
    'BEGIN':          BLUE,
    'WAIT_FOR_SETTLE': AMBER,
    'ELEVONS':        AMBER,
    'RUDDERS':        AMBER,
    'TVC':            AMBER,
    '✓ COMPLETE':     GREEN,
    '✓ PASS':         GREEN,
    '✗ FAIL':         RED,
}
