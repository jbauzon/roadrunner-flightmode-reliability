"""DAQ setup and test configuration widgets."""
from __future__ import annotations

from PyQt5.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QComboBox, QSpinBox, QLineEdit, QCheckBox, QRadioButton, QButtonGroup,
    QWidget, QFileDialog,
)
from PyQt5.QtCore import pyqtSignal, Qt

from .. import theme as T
from .primitives import LED, _label, _sep, _section_title
from vehicle.constants import TestMode


# ═══════════════════════════════════════════════════════════════════════════════
# DAQ Setup Widget
# ═══════════════════════════════════════════════════════════════════════════════

class DAQSetupWidget(QGroupBox):
    detect_clicked    = pyqtSignal()
    initialize_clicked = pyqtSignal()
    sitl_clicked      = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("Hardware Interface", parent)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 16, 12, 10)
        layout.setSpacing(8)

        # Row 1: Device selector
        row1 = QHBoxLayout()
        row1.setSpacing(8)
        row1.addWidget(_label("DAQ Device:", T.TEXT_SECONDARY))
        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(120)
        self.device_combo.setToolTip("NI-DAQmx device that controls relay lines")
        row1.addWidget(self.device_combo, 1)
        layout.addLayout(row1)

        # Row 2: Buttons
        row2 = QHBoxLayout()
        row2.setSpacing(8)
        self.detect_btn = QPushButton("Detect")
        self.detect_btn.setMinimumWidth(70)
        self.detect_btn.setToolTip("Scan for connected NI-DAQmx devices (F5)")
        self.detect_btn.clicked.connect(self.detect_clicked)
        row2.addWidget(self.detect_btn)

        self.init_btn = QPushButton("Initialize")
        self.init_btn.setMinimumWidth(80)
        self.init_btn.setToolTip("Initialize selected DAQ device")
        self.init_btn.clicked.connect(self.initialize_clicked)
        row2.addWidget(self.init_btn)
        row2.addStretch()
        layout.addLayout(row2)

        # Row 2b: SITL mode — small, low-contrast, dev/test use only
        row2b = QHBoxLayout()
        row2b.setSpacing(8)
        self.sitl_btn = QPushButton("Simulate")
        self.sitl_btn.setMinimumWidth(70)
        self.sitl_btn.setMaximumHeight(22)
        self.sitl_btn.setToolTip(
            "Simulation mode — starts virtual vehicles on localhost.\n"
            "No NI-DAQmx hardware required. For development and testing only."
        )
        self.sitl_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {T.TEXT_DISABLED}; "
            f"border: 1px solid {T.BORDER}; border-radius: 3px; "
            f"padding: 2px 8px; font-size: {T.FONT_SIZE_SM}; }}"
            f"QPushButton:hover {{ color: {T.TEXT_SECONDARY}; "
            f"border-color: {T.TEXT_DISABLED}; }}"
        )
        self.sitl_btn.clicked.connect(self.sitl_clicked)
        row2b.addWidget(self.sitl_btn)
        row2b.addStretch()
        layout.addLayout(row2b)

        # Row 3: Status
        row3 = QHBoxLayout()
        row3.setSpacing(8)
        self.status_led = LED()
        self.status_led.set_state('amber')
        row3.addWidget(self.status_led)
        self.status_label = QLabel("Not Initialized")
        self.status_label.setStyleSheet(
            f"color: {T.AMBER}; font-weight: bold; background: transparent;"
        )
        row3.addWidget(self.status_label)
        row3.addStretch()
        layout.addLayout(row3)

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

    def set_sitl_active(self):
        """Update the widget to show SITL mode is active."""
        self.sitl_btn.setEnabled(False)
        self.sitl_btn.setText("SITL Active")
        self.detect_btn.setEnabled(False)
        self.init_btn.setEnabled(False)
        self.device_combo.setEnabled(False)
        self.set_status(True, "SITL Mode (Simulated)")


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
        self.log_dir_input.setToolTip(self.log_directory)
        self.log_dir_input.setCursorPosition(len(self.log_directory))
        # Show the end of the path so the user sees the folder name, not "C:\And..."
        self.log_dir_input.setAlignment(Qt.AlignRight)
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
        self._adv_toggle_btn = QPushButton("Advanced Settings  \u25be  (timeouts, ARM retries)")
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
        tooltips_map = {
            "Connection Timeout": "Seconds to wait for initial MAVLink connection",
            "Stabilization Delay": "Seconds to wait after enabling relay before testing",
            "Max ARM Iterations": "Maximum ARM attempts with monitor clearing before giving up",
        }
        for i, (lbl_text, attr, widget_cls, args) in enumerate(params):
            adv_layout.addWidget(_label(lbl_text + ":", T.TEXT_SECONDARY), i, 0)
            w = widget_cls()
            lo, hi, val, suffix = args
            w.setRange(lo, hi)
            w.setValue(val)
            if suffix:
                w.setSuffix(suffix)
            tip = tooltips_map.get(lbl_text)
            if tip:
                w.setToolTip(tip)
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
            "Advanced Settings  \u25b4" if self._adv_visible
            else "Advanced Settings  \u25be  (timeouts, ARM retries)"
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
        self.log_dir_input.setToolTip(directory)
        self.log_dir_input.setCursorPosition(len(directory))
        # Show the end of the path so the user sees the folder name, not "C:\And..."
        self.log_dir_input.setAlignment(Qt.AlignRight)
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
