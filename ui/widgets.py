"""
UI Widgets - Modern operator console components.

All widgets use the dark theme from ui/theme.py.
Each widget is self-contained and manages its own state.
"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel, QPushButton,
    QComboBox, QSpinBox, QLineEdit, QTableWidget, QTableWidgetItem,
    QTextEdit, QProgressBar, QCheckBox, QDialog, QDialogButtonBox,
    QGridLayout, QHeaderView, QFrame, QFileDialog, QButtonGroup,
    QRadioButton, QSizePolicy, QScrollArea, QTabWidget
)
from PyQt5.QtCore import pyqtSignal, Qt, QTimer
from PyQt5.QtGui import QColor, QFont
from datetime import datetime
import time

from . import theme as T
from vehicle.constants import (
    TestMode, MODE_NAMES, FLIGHT_REGIME_SHORT_NAMES, UUTStatus, ActuationMode,
    get_mode_name, get_flight_regime_short_name,
)


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


# ═══════════════════════════════════════════════════════════════════════════════
# Header Banner
# ═══════════════════════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════════════════════
# DAQ Setup Widget
# ═══════════════════════════════════════════════════════════════════════════════

class DAQSetupWidget(QGroupBox):
    detect_clicked    = pyqtSignal()
    initialize_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("Hardware Interface", parent)
        self._init_ui()

    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 16, 12, 10)
        layout.setSpacing(10)

        layout.addWidget(_label("DAQ Device:", T.TEXT_SECONDARY))

        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(160)
        self.device_combo.setToolTip("NI-DAQmx device that controls relay lines")
        layout.addWidget(self.device_combo)

        self.detect_btn = QPushButton("Detect")
        self.detect_btn.setToolTip("Scan for connected NI-DAQmx devices")
        self.detect_btn.clicked.connect(self.detect_clicked)
        layout.addWidget(self.detect_btn)

        self.init_btn = QPushButton("Initialize")
        self.init_btn.setToolTip("Initialize selected DAQ device")
        self.init_btn.clicked.connect(self.initialize_clicked)
        layout.addWidget(self.init_btn)

        layout.addSpacing(16)

        self.status_led  = LED()
        layout.addWidget(self.status_led)

        self.status_label = QLabel("Not Initialized")
        self.status_label.setStyleSheet(
            f"color: {T.TEXT_DISABLED}; font-weight: bold; background: transparent;"
        )
        layout.addWidget(self.status_label)
        layout.addStretch()

    def set_devices(self, devices):
        self.device_combo.clear()
        self.device_combo.addItems(devices)

    def get_selected_device(self):
        return self.device_combo.currentText()

    def set_status(self, initialized, message):
        self.status_label.setText(message)
        if initialized:
            self.status_led.set_state('green')
            self.status_label.setStyleSheet(
                f"color: {T.GREEN}; font-weight: bold; background: transparent;"
            )
        else:
            self.status_led.set_state('red')
            self.status_label.setStyleSheet(
                f"color: {T.RED}; font-weight: bold; background: transparent;"
            )


# ═══════════════════════════════════════════════════════════════════════════════
# Test Configuration Widget
# ═══════════════════════════════════════════════════════════════════════════════

class TestConfigWidget(QGroupBox):
    log_dir_changed = pyqtSignal(str)
    browse_clicked  = pyqtSignal()
    open_clicked    = pyqtSignal()
    mode_changed    = pyqtSignal(str)

    def __init__(self, log_directory, parent=None):
        super().__init__("Test Configuration", parent)
        self.log_directory = log_directory
        self._init_ui()

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 16, 12, 10)
        root.setSpacing(12)

        # ── Mode selector ────────────────────────────────────────────────
        root.addWidget(_section_title("Test Mode"))
        mode_row = QHBoxLayout()
        mode_row.setSpacing(8)

        self.mode_ibit_radio     = QRadioButton("  IBIT")
        self.mode_playback_radio = QRadioButton("  Flight Profile Playback")
        self.mode_ibit_radio.setChecked(True)
        self._mode_group = QButtonGroup()
        self._mode_group.addButton(self.mode_ibit_radio)
        self._mode_group.addButton(self.mode_playback_radio)

        for rb in (self.mode_ibit_radio, self.mode_playback_radio):
            rb.setStyleSheet(
                f"QRadioButton {{ font-size: {T.FONT_SIZE}; font-weight: bold; "
                f"color: {T.TEXT_PRIMARY}; padding: 6px 12px; background: {T.BG_ELEVATED}; "
                f"border: 1px solid {T.BORDER}; border-radius: 6px; }}"
                f"QRadioButton:checked {{ border-color: {T.BLUE}; color: {T.BLUE}; "
                f"background: {T.BLUE_DIM}; }}"
                f"QRadioButton::indicator {{ width: 0; height: 0; }}"
            )
            mode_row.addWidget(rb)

        mode_row.addStretch()
        root.addLayout(mode_row)
        self.mode_ibit_radio.toggled.connect(self._on_mode_changed)

        # ── Playback options (hidden by default) ─────────────────────────
        self.playback_group = QGroupBox("Playback Options")
        pb_layout = QGridLayout(self.playback_group)
        pb_layout.setContentsMargins(10, 14, 10, 10)
        pb_layout.setSpacing(8)

        pb_layout.addWidget(_label("Profile CSV:", T.TEXT_SECONDARY), 0, 0)
        self.playback_csv_input = QLineEdit()
        self.playback_csv_input.setReadOnly(True)
        self.playback_csv_input.setPlaceholderText("Select flight profile CSV...")
        pb_layout.addWidget(self.playback_csv_input, 0, 1)
        browse_csv_btn = QPushButton("Browse")
        browse_csv_btn.clicked.connect(self._browse_playback_csv)
        pb_layout.addWidget(browse_csv_btn, 0, 2)

        pb_layout.addWidget(_label("Type:", T.TEXT_SECONDARY), 1, 0)
        self.playback_type_combo = QComboBox()
        self.playback_type_combo.addItems(["Actuation", "Propulsion", "Both"])
        pb_layout.addWidget(self.playback_type_combo, 1, 1)

        self.playback_frames_label = _label("No profile loaded", T.TEXT_DISABLED)
        pb_layout.addWidget(self.playback_frames_label, 2, 0, 1, 3)

        self.playback_group.setVisible(False)
        root.addWidget(self.playback_group)

        root.addWidget(_sep())

        # ── Options ──────────────────────────────────────────────────────
        root.addWidget(_section_title("Options"))
        self.skip_state_mgmt_checkbox = QCheckBox("Skip State Management  (faster, less safe)")
        self.skip_arm_checkbox        = QCheckBox("Skip ARM requirement  (test while disarmed)")
        for cb in (self.skip_state_mgmt_checkbox, self.skip_arm_checkbox):
            cb.setStyleSheet(
                f"QCheckBox {{ color: {T.TEXT_SECONDARY}; font-size: {T.FONT_SIZE_SM}; "
                f"background: transparent; }}"
            )
            root.addWidget(cb)

        root.addWidget(_sep())

        # ── Log directory ─────────────────────────────────────────────────
        root.addWidget(_section_title("Log Directory"))
        dir_row = QHBoxLayout()
        dir_row.setSpacing(6)
        self.log_dir_input = QLineEdit()
        self.log_dir_input.setReadOnly(True)
        self.log_dir_input.setText(self.log_directory)
        dir_row.addWidget(self.log_dir_input)
        browse_dir_btn = QPushButton("Browse")
        browse_dir_btn.clicked.connect(self.browse_clicked)
        dir_row.addWidget(browse_dir_btn)
        open_dir_btn = QPushButton("Open")
        open_dir_btn.clicked.connect(self.open_clicked)
        dir_row.addWidget(open_dir_btn)
        root.addLayout(dir_row)

        root.addWidget(_sep())

        # ── Duration + Advanced (tabs) ────────────────────────────────────
        root.addWidget(_section_title("Duration"))
        dur_row = QHBoxLayout()
        dur_row.setSpacing(8)
        self.duration_input = QSpinBox()
        self.duration_input.setRange(1, 99999)
        self.duration_input.setValue(14)
        dur_row.addWidget(self.duration_input)
        self.duration_unit_combo = QComboBox()
        self.duration_unit_combo.addItems(["Seconds", "Minutes", "Hours", "Days"])
        self.duration_unit_combo.setCurrentText("Days")
        dur_row.addWidget(self.duration_unit_combo)
        dur_row.addStretch()
        root.addLayout(dur_row)

        # Advanced (collapsible via button)
        self._adv_visible = False
        self._adv_toggle_btn = QPushButton("Advanced Settings  ▾")
        self._adv_toggle_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {T.TEXT_SECONDARY}; "
            f"border: none; font-size: {T.FONT_SIZE_SM}; text-align: left; padding: 2px 0; }}"
            f"QPushButton:hover {{ color: {T.TEXT_PRIMARY}; }}"
        )
        self._adv_toggle_btn.clicked.connect(self._toggle_advanced)
        root.addWidget(self._adv_toggle_btn)

        self._adv_widget = QWidget()
        adv_layout = QGridLayout(self._adv_widget)
        adv_layout.setContentsMargins(0, 4, 0, 0)
        adv_layout.setSpacing(6)

        params = [
            ("Connection Timeout",  "connection_timeout_input",  QSpinBox, (1,  60,  10, " s")),
            ("Stabilization Delay", "stabilization_delay_input", QSpinBox, (0,  10,   2, " s")),
            ("IBIT Timeout",        "ibit_timeout_input",        QSpinBox, (30, 600, 300, " s")),
            ("Phase Timeout",       "phase_timeout_input",       QSpinBox, (10, 300,  90, " s")),
            ("ARM Timeout",         "arm_timeout_input",         QSpinBox, (10, 300,  60, " s")),
            ("Max ARM Iterations",  "max_arm_iterations_input",  QSpinBox, (1,  100,  20, "")),
        ]
        for i, (lbl_text, attr, widget_cls, args) in enumerate(params):
            adv_layout.addWidget(_label(lbl_text + ":", T.TEXT_SECONDARY), i, 0)
            w = widget_cls()
            lo, hi, val, suffix = args
            w.setRange(lo, hi)
            w.setValue(val)
            if suffix:
                w.setSuffix(suffix)
            setattr(self, attr, w)
            adv_layout.addWidget(w, i, 1)

        self._adv_widget.setVisible(False)
        root.addWidget(self._adv_widget)
        root.addStretch()

    # ── Slots ────────────────────────────────────────────────────────────

    def _toggle_advanced(self):
        self._adv_visible = not self._adv_visible
        self._adv_widget.setVisible(self._adv_visible)
        self._adv_toggle_btn.setText(
            "Advanced Settings  ▴" if self._adv_visible else "Advanced Settings  ▾"
        )

    def _on_mode_changed(self, ibit_selected):
        self.playback_group.setVisible(not ibit_selected)
        self.mode_changed.emit(TestMode.IBIT if ibit_selected else TestMode.PLAYBACK)

    def _browse_playback_csv(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Flight Profile CSV", "", "CSV Files (*.csv)"
        )
        if path:
            self.playback_csv_input.setText(path)
            # Count frames
            try:
                with open(path) as f:
                    lines = sum(1 for _ in f) - 1
                self.playback_frames_label.setText(
                    f"{lines:,} frames  ({lines/100:.1f}s at 100 Hz)"
                )
                self.playback_frames_label.setStyleSheet(
                    f"color: {T.GREEN}; background: transparent; "
                    f"font-size: {T.FONT_SIZE_SM};"
                )
            except Exception:
                self.playback_frames_label.setText("Could not read frame count")
                self.playback_frames_label.setStyleSheet(
                    f"color: {T.AMBER}; background: transparent; "
                    f"font-size: {T.FONT_SIZE_SM};"
                )

    # ── Accessors ────────────────────────────────────────────────────────

    def get_test_mode(self):
        return TestMode.IBIT if self.mode_ibit_radio.isChecked() else TestMode.PLAYBACK

    def get_playback_csv(self):
        return self.playback_csv_input.text()

    def get_playback_type(self):
        return self.playback_type_combo.currentText()

    def set_log_directory(self, directory):
        self.log_directory = directory
        self.log_dir_input.setText(directory)
        self.log_dir_changed.emit(directory)

    def get_duration(self):
        return self.duration_input.value(), self.duration_unit_combo.currentText()

    def get_connection_timeout(self):
        return self.connection_timeout_input.value()

    def get_stabilization_delay(self):
        return self.stabilization_delay_input.value()

    def get_skip_state_management(self):
        return self.skip_state_mgmt_checkbox.isChecked()

    def get_config(self):
        return {
            'ibit_timeout':       self.ibit_timeout_input.value(),
            'phase_timeout':      self.phase_timeout_input.value(),
            'arm_timeout':        self.arm_timeout_input.value(),
            'max_arm_iterations': self.max_arm_iterations_input.value(),
            'skip_arm_for_ibit':  self.skip_arm_checkbox.isChecked(),
            'test_mode':          self.get_test_mode(),
            'playback_csv':       self.get_playback_csv(),
            'playback_type':      self.get_playback_type(),
        }

    def get_all_settings(self):
        return {
            'connection_timeout':  self.connection_timeout_input.value(),
            'stabilization_delay': self.stabilization_delay_input.value(),
            'skip_state_management': self.skip_state_mgmt_checkbox.isChecked(),
            'skip_arm_for_ibit':   self.skip_arm_checkbox.isChecked(),
            'ibit_timeout':        self.ibit_timeout_input.value(),
            'phase_timeout':       self.phase_timeout_input.value(),
            'arm_timeout':         self.arm_timeout_input.value(),
            'max_arm_iterations':  self.max_arm_iterations_input.value(),
            'test_mode':           self.get_test_mode(),
            'playback_csv':        self.get_playback_csv(),
            'playback_type':       self.get_playback_type(),
        }

    def load_settings(self, settings):
        self.connection_timeout_input.setValue(settings.get('connection_timeout', 10))
        self.stabilization_delay_input.setValue(settings.get('stabilization_delay', 2))
        self.skip_state_mgmt_checkbox.setChecked(settings.get('skip_state_management', False))
        self.skip_arm_checkbox.setChecked(settings.get('skip_arm_for_ibit', False))
        self.ibit_timeout_input.setValue(settings.get('ibit_timeout', 300))
        self.phase_timeout_input.setValue(settings.get('phase_timeout', 90))
        self.arm_timeout_input.setValue(settings.get('arm_timeout', 60))
        self.max_arm_iterations_input.setValue(settings.get('max_arm_iterations', 20))
        if settings.get('test_mode', TestMode.IBIT) == TestMode.PLAYBACK:
            self.mode_playback_radio.setChecked(True)
        else:
            self.mode_ibit_radio.setChecked(True)
        if settings.get('playback_csv'):
            self.playback_csv_input.setText(settings['playback_csv'])
        if settings.get('playback_type'):
            idx = self.playback_type_combo.findText(settings['playback_type'])
            if idx >= 0:
                self.playback_type_combo.setCurrentIndex(idx)


# ═══════════════════════════════════════════════════════════════════════════════
# UUT Table Widget
# ═══════════════════════════════════════════════════════════════════════════════

class UUTTableWidget(QGroupBox):
    add_clicked    = pyqtSignal()
    edit_clicked   = pyqtSignal()
    remove_clicked = pyqtSignal()
    save_clicked   = pyqtSignal()
    load_clicked   = pyqtSignal()

    _STATUS_COLORS = {
        "Ready":       (T.BG_ELEVATED,  T.TEXT_SECONDARY),
        "Testing":     (T.BLUE_DIM,     T.BLUE),
        "Complete":    (T.GREEN_DIM,    T.GREEN),
        "Failed":      (T.RED_DIM,      T.RED),
        "Failed (3x)": (T.RED_DIM,      T.RED),
        "Retry":       (T.AMBER_DIM,    T.AMBER),
        "Stopped":     (T.BG_ELEVATED,  T.TEXT_DISABLED),
    }

    def __init__(self, parent=None):
        super().__init__("Unit Under Test", parent)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 16, 12, 10)
        layout.setSpacing(8)

        # Toolbar
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)

        btn_styles = [
            ("+ Add",    self.add_clicked,    False),
            ("Edit",     self.edit_clicked,   False),
            ("Remove",   self.remove_clicked, True),
            ("Save",     self.save_clicked,   False),
            ("Load",     self.load_clicked,   False),
        ]
        for label, signal, danger in btn_styles:
            btn = QPushButton(label)
            if danger:
                btn.setStyleSheet(
                    f"QPushButton {{ background: {T.RED_DIM}; color: {T.RED}; "
                    f"border: 1px solid {T.RED_DIM}; border-radius: 5px; "
                    f"padding: 5px 12px; font-size: {T.FONT_SIZE_SM}; }}"
                    f"QPushButton:hover {{ background: {T.RED}; color: {T.WHITE}; }}"
                )
            else:
                btn.setStyleSheet(
                    f"QPushButton {{ background: {T.BG_ELEVATED}; color: {T.TEXT_PRIMARY}; "
                    f"border: 1px solid {T.BORDER}; border-radius: 5px; "
                    f"padding: 5px 12px; font-size: {T.FONT_SIZE_SM}; }}"
                    f"QPushButton:hover {{ border-color: {T.TEXT_SECONDARY}; }}"
                )
            btn.clicked.connect(signal)
            toolbar.addWidget(btn)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(["#", "Serial", "IP Address", "Port", "Relay", "Iterations", "Status"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet(
            f"QTableWidget::item:alternate {{ background-color: {T.BG_BASE}; }}"
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        layout.addWidget(self.table)

    def update_table(self, uuts):
        """Refresh the table from a list of UUT objects."""
        self.table.setRowCount(len(uuts))
        for i, uut in enumerate(uuts):
            items = [
                str(i + 1),
                uut.serial_number,
                uut.ip_address,
                str(uut.port),
                f"D{uut.relay_line}",
                str(uut.iterations_completed),
                uut.status,
            ]
            for j, val in enumerate(items):
                item = QTableWidgetItem(val)
                item.setTextAlignment(Qt.AlignCenter)
                if j == 6:  # Status column
                    bg, fg = self._STATUS_COLORS.get(uut.status, (T.BG_ELEVATED, T.TEXT_SECONDARY))
                    item.setBackground(QColor(bg))
                    item.setForeground(QColor(fg))
                    f = item.font()
                    f.setBold(True)
                    item.setFont(f)
                self.table.setItem(i, j, item)
        self.table.resizeRowsToContents()

    def get_selected_row(self):
        """Return the selected row index, or -1 if none."""
        selected = self.table.selectionModel().selectedRows()
        return selected[0].row() if selected else -1


# ═══════════════════════════════════════════════════════════════════════════════
# Status Panel Widget
# ═══════════════════════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════════════════════
# IBIT / Playback Display Widget
# ═══════════════════════════════════════════════════════════════════════════════

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
            dot.setFixedSize(10, 10)
            dot.setStyleSheet(f"background-color: {T.BG_ELEVATED}; border-radius: 5px;")
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
            "Phases: BEGIN → SETTLE → ELEVONS → RUDDERS → TVC",
            T.TEXT_DISABLED, size=T.FONT_SIZE_SM
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
            "Streaming 100 Hz flight profile — real-time surface tracking"
            if is_pb else
            "Phases: BEGIN → SETTLE → ELEVONS → RUDDERS → TVC"
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
                dot.setStyleSheet(f"background-color: {T.GREEN}; border-radius: 5px;")
            elif i == current_idx:
                dot.setStyleSheet(f"background-color: {T.AMBER}; border-radius: 5px;")
            else:
                dot.setStyleSheet(f"background-color: {T.BG_ELEVATED}; border-radius: 5px;")
        if substate_name == "✓ COMPLETE":
            for dot in self._phase_dots:
                dot.setStyleSheet(f"background-color: {T.GREEN}; border-radius: 5px;")

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
            dot.setStyleSheet(f"background-color: {T.BG_ELEVATED}; border-radius: 5px;")
        self.playback_bar.setValue(0)
        self.playback_pct_label.setText("0%")
        self.duration_label.setText("00:00  (0.0s)")
        self.mistracking_badge.set_text_color("NONE", T.GREEN_DIM, T.GREEN)


# ═══════════════════════════════════════════════════════════════════════════════
# Actuator Feedback Widget
# ═══════════════════════════════════════════════════════════════════════════════

class ActuatorFeedbackWidget(QGroupBox):
    def __init__(self, parent=None):
        super().__init__("Actuator Feedback", parent)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 16, 12, 10)
        layout.setSpacing(6)

        # Header
        hdr = QGridLayout()
        hdr.setSpacing(4)
        for i, (txt, col) in enumerate([
            ("Surface", 0), ("Cmd °", 1), ("Fdbk °", 2),
            ("Δ °", 3), ("mA", 4), ("°C", 5)
        ]):
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

            cmd   = _label("---", mono=True, size=T.FONT_SIZE_SM)
            fb    = _label("---", mono=True, size=T.FONT_SIZE_SM)
            delta = _label("---", mono=True, size=T.FONT_SIZE_SM)
            curr  = _label("---", mono=True, size=T.FONT_SIZE_SM)
            temp  = _label("---", mono=True, size=T.FONT_SIZE_SM)

            for col_idx, w in enumerate([cmd, fb, delta, curr, temp], start=1):
                w.setAlignment(Qt.AlignCenter)
                self._grid.addWidget(w, row_idx, col_idx)

            self._rows[key] = {
                'cmd': cmd, 'fb': fb, 'delta': delta, 'curr': curr, 'temp': temp
            }

        layout.addLayout(self._grid)

        self.last_update_label = _label("Last update: —", T.TEXT_DISABLED, size=T.FONT_SIZE_SM)
        layout.addWidget(self.last_update_label)

    def _delta_color(self, d):
        if d < 0.5:
            return T.GREEN
        elif d < 1.0:
            return T.AMBER
        return T.RED

    def update_feedback(self, data):
        """Update all surface rows from a feedback data dict."""
        try:
            keys = [
                "left_elevon", "right_elevon",
                "dorsal_rudder", "ventral_rudder",
                "left_tvc_upper", "left_tvc_lower",
                "right_tvc_upper", "right_tvc_lower",
            ]
            for key in keys:
                row = self._rows[key]
                fb_raw  = data.get(f"{key}_feedback_cdeg")
                cmd_raw = data.get(f"{key}_cmd_cdeg")
                curr    = data.get(f"{key}_current_mA")
                temp    = data.get(f"{key}_motor_temp_degC")

                fb_deg  = fb_raw  / 100.0 if fb_raw  is not None else None
                cmd_deg = cmd_raw / 100.0 if cmd_raw is not None else None

                row['cmd'].setText( f"{cmd_deg:.1f}" if cmd_deg is not None else "---")
                row['fb'].setText(  f"{fb_deg:.1f}"  if fb_deg  is not None else "---")

                if cmd_deg is not None and fb_deg is not None:
                    d = abs(cmd_deg - fb_deg)
                    color = self._delta_color(d)
                    row['delta'].setText(f"{d:.1f}")
                    row['delta'].setStyleSheet(
                        f"color: {color}; font-family: {T.FONT_MONO}; "
                        f"font-size: {T.FONT_SIZE_SM}; background: transparent; font-weight: bold;"
                    )
                else:
                    row['delta'].setText("---")
                    row['delta'].setStyleSheet(
                        f"color: {T.TEXT_DISABLED}; font-family: {T.FONT_MONO}; "
                        f"font-size: {T.FONT_SIZE_SM}; background: transparent;"
                    )

                row['curr'].setText(str(curr) if curr is not None else "---")
                row['temp'].setText(str(temp) if temp is not None else "---")

            self.last_update_label.setText(
                f"Last update: {datetime.now().strftime('%H:%M:%S.%f')[:-4]}"
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
        self.last_update_label.setText("Last update: —")


# ═══════════════════════════════════════════════════════════════════════════════
# Alert Banner
# ═══════════════════════════════════════════════════════════════════════════════

class AlertBannerWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setVisible(False)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 8)

        self._icon = QLabel("⚠")
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

        self._dismiss = QPushButton("✕")
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
            'warning':  (T.AMBER_DIM, T.AMBER,  T.AMBER,  "⚠"),
            'error':    (T.RED_DIM,   T.RED,    T.RED,    "✗"),
            'critical': (T.RED,       T.WHITE,  T.WHITE,  "⚠⚠⚠"),
            'info':     (T.BLUE_DIM,  T.BLUE,   T.BLUE,   "ℹ"),
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


# ═══════════════════════════════════════════════════════════════════════════════
# Progress Widget
# ═══════════════════════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════════════════════
# Control Buttons
# ═══════════════════════════════════════════════════════════════════════════════

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

        self.start_btn = QPushButton("▶  Start IBIT Test")
        self.start_btn.setStyleSheet(T.btn_primary())
        self.start_btn.setMinimumHeight(52)
        self.start_btn.clicked.connect(self.start_clicked)
        layout.addWidget(self.start_btn, 3)

        self.stop_btn = QPushButton("⏹  Stop")
        self.stop_btn.setStyleSheet(T.btn_danger())
        self.stop_btn.setMinimumHeight(52)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_clicked)
        layout.addWidget(self.stop_btn, 1)

        self.emergency_btn = QPushButton("⚡  EMERGENCY STOP")
        self.emergency_btn.setStyleSheet(T.btn_emergency())
        self.emergency_btn.clicked.connect(self.emergency_clicked)
        layout.addWidget(self.emergency_btn, 2)

    def set_testing_mode(self, testing):
        """Enable/disable buttons for testing state."""
        self.start_btn.setEnabled(not testing)
        self.stop_btn.setEnabled(testing)

    def set_test_mode_label(self, mode):
        """Update the start button label for the current test mode."""
        if mode == TestMode.PLAYBACK:
            self.start_btn.setText("▶  Start Playback Test")
        else:
            self.start_btn.setText("▶  Start IBIT Test")

    def set_enabled(self, start_enabled, stop_enabled):
        """Explicitly set button enabled states."""
        self.start_btn.setEnabled(start_enabled)
        self.stop_btn.setEnabled(stop_enabled)


# ═══════════════════════════════════════════════════════════════════════════════
# Log Widget
# ═══════════════════════════════════════════════════════════════════════════════

class LogWidget(QGroupBox):
    def __init__(self, parent=None):
        super().__init__("Test Log", parent)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 16, 12, 10)
        layout.setSpacing(6)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(220)
        self.log_text.setMaximumHeight(420)
        layout.addWidget(self.log_text)

        bar = QHBoxLayout()
        bar.addStretch()
        clear_btn = QPushButton("Clear")
        clear_btn.setStyleSheet(
            f"QPushButton {{ background: {T.BG_ELEVATED}; color: {T.TEXT_SECONDARY}; "
            f"border: 1px solid {T.BORDER}; border-radius: 4px; "
            f"padding: 3px 10px; font-size: {T.FONT_SIZE_SM}; }}"
            f"QPushButton:hover {{ color: {T.TEXT_PRIMARY}; }}"
        )
        clear_btn.clicked.connect(self.log_text.clear)
        bar.addWidget(clear_btn)
        layout.addLayout(bar)

    def append(self, message):
        """Append a timestamped, color-coded message to the log."""
        ts = datetime.now().strftime('%H:%M:%S')

        # Color-code by prefix
        if '✓' in message or 'PASS' in message.upper():
            color = T.GREEN
        elif '✗' in message or 'FAIL' in message.upper() or 'ERROR' in message.upper():
            color = T.RED
        elif '⚠' in message or 'WARNING' in message.upper():
            color = T.AMBER
        elif message.startswith('═') or message.startswith('='):
            color = T.TEXT_SECONDARY
        else:
            color = T.GREEN

        html = (
            f'<span style="color:{T.TEXT_DISABLED};">[{ts}] </span>'
            f'<span style="color:{color};">{message}</span>'
        )
        self.log_text.append(html)
        sb = self.log_text.verticalScrollBar()
        sb.setValue(sb.maximum())


# ═══════════════════════════════════════════════════════════════════════════════
# Add/Edit UUT Dialog
# ═══════════════════════════════════════════════════════════════════════════════

class AddUUTDialog(QDialog):
    def __init__(self, parent=None, uut=None):
        super().__init__(parent)
        self.uut = uut
        self._init_ui()
        if uut:
            self._load_uut()

    def _init_ui(self):
        self.setWindowTitle("Configure UUT")
        self.setModal(True)
        self.setMinimumWidth(360)
        self.setStyleSheet(f"QDialog {{ background-color: {T.BG_SURFACE}; }}")

        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(20, 20, 20, 16)

        title = _label("Unit Under Test", bold=True, size=T.FONT_SIZE_LG)
        layout.addWidget(title)
        layout.addWidget(_sep())

        form = QGridLayout()
        form.setSpacing(10)
        form.setColumnStretch(1, 1)

        fields = [
            ("Serial Number:", "serial_input",  QLineEdit,  {}),
            ("IP Address:",    "ip_input",       QLineEdit,  {"placeholder": "192.168.1.100"}),
            ("Port:",          "port_input",     QSpinBox,   {"range": (1, 65535), "value": 9985}),
            ("Relay Line:",    "relay_input",    QSpinBox,   {"range": (0, 31),    "value": 0}),
        ]

        for i, (lbl_text, attr, widget_cls, opts) in enumerate(fields):
            form.addWidget(_label(lbl_text, T.TEXT_SECONDARY), i, 0)
            if widget_cls == QLineEdit:
                w = QLineEdit()
                if opts.get("placeholder"):
                    w.setPlaceholderText(opts["placeholder"])
            elif widget_cls == QSpinBox:
                w = QSpinBox()
                lo, hi = opts.get("range", (0, 100))
                w.setRange(lo, hi)
                w.setValue(opts.get("value", 0))
            setattr(self, attr, w)
            form.addWidget(w, i, 1)

        layout.addLayout(form)

        # Tip
        tip = _label(
            "Relay line must match the DAQ digital output channel "
            "wired to this vehicle's power supply.",
            T.TEXT_DISABLED, size=T.FONT_SIZE_SM
        )
        tip.setWordWrap(True)
        layout.addWidget(tip)

        layout.addWidget(_sep())

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _load_uut(self):
        self.serial_input.setText(self.uut.serial_number)
        self.ip_input.setText(self.uut.ip_address)
        self.port_input.setValue(self.uut.port)
        self.relay_input.setValue(self.uut.relay_line)

    def get_uut(self):
        """Return a new UUT from the dialog's field values."""
        from vehicle.connection import UUT
        return UUT(
            serial_number=self.serial_input.text(),
            ip_address=self.ip_input.text(),
            port=self.port_input.value(),
            relay_line=self.relay_input.value()
        )
