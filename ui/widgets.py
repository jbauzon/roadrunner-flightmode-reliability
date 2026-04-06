"""
UI Widgets - Reusable UI components for the main window

This module contains all the individual widgets used in the main application window.
Each widget is self-contained and manages its own internal state.
"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel, QPushButton,
    QComboBox, QSpinBox, QLineEdit, QTableWidget, QTableWidgetItem,
    QTextEdit, QProgressBar, QCheckBox, QDialog, QDialogButtonBox,
    QGridLayout, QHeaderView, QFrame, QFileDialog, QButtonGroup, QRadioButton
)
from PyQt5.QtCore import pyqtSignal, Qt, QTimer
from PyQt5.QtGui import QColor, QFont
from datetime import datetime
import time


# ============================================================
# DAQ Setup Widget
# ============================================================

class DAQSetupWidget(QGroupBox):
    """
    DAQ hardware setup and initialization widget.
    
    Signals:
        detect_clicked: User clicked "Detect Devices"
        initialize_clicked: User clicked "Initialize DAQ"
    """
    
    detect_clicked = pyqtSignal()
    initialize_clicked = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__("DAQ Setup", parent)
        self.init_ui()
    
    def init_ui(self):
        """Initialize UI components"""
        layout = QHBoxLayout()
        
        layout.addWidget(QLabel("Device:"))
        
        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(150)
        layout.addWidget(self.device_combo)
        
        self.detect_btn = QPushButton("Detect Devices")
        self.detect_btn.clicked.connect(self.detect_clicked)
        layout.addWidget(self.detect_btn)
        
        self.init_btn = QPushButton("Initialize DAQ")
        self.init_btn.clicked.connect(self.initialize_clicked)
        layout.addWidget(self.init_btn)
        
        self.status_label = QLabel("Not Initialized")
        self.status_label.setStyleSheet("color: red; font-weight: bold;")
        layout.addWidget(self.status_label)
        
        layout.addStretch()
        
        self.setLayout(layout)
    
    def set_devices(self, devices):
        """
        Set available devices in combo box.
        
        Args:
            devices: List of device names
        """
        self.device_combo.clear()
        self.device_combo.addItems(devices)
    
    def get_selected_device(self):
        """
        Get currently selected device.
        
        Returns:
            str: Device name or empty string
        """
        return self.device_combo.currentText()
    
    def set_status(self, initialized, message):
        """
        Set DAQ status display.
        
        Args:
            initialized: True if DAQ is initialized
            message: Status message
        """
        self.status_label.setText(message)
        if initialized:
            self.status_label.setStyleSheet("color: green; font-weight: bold;")
        else:
            self.status_label.setStyleSheet("color: red; font-weight: bold;")


# ============================================================
# Test Configuration Widget
# ============================================================

class TestConfigWidget(QGroupBox):
    """
    Test configuration panel.
    
    Signals:
        log_dir_changed: Log directory changed (emits directory path)
        browse_clicked: Browse button clicked
        open_clicked: Open directory button clicked
    """
    
    log_dir_changed = pyqtSignal(str)
    browse_clicked = pyqtSignal()
    open_clicked = pyqtSignal()
    mode_changed = pyqtSignal(str)  # emits 'ibit' or 'playback'
    
    def __init__(self, log_directory, parent=None):
        super().__init__("Test Configuration", parent)
        self.log_directory = log_directory
        self.init_ui()
    
    def init_ui(self):
        """Initialize UI components"""
        layout = QGridLayout()
        
        # Info label
        info_label = QLabel(
            "v5.0 — IBIT and Flight Profile Playback test modes with descriptive CSV logging"
        )
        info_label.setStyleSheet(
            "color: #1976D2; font-style: italic; font-size: 10pt;"
        )
        layout.addWidget(info_label, 0, 0, 1, 4)
        
        # Test mode selector
        mode_group = QGroupBox("Test Mode")
        mode_layout = QHBoxLayout()
        self.mode_ibit_radio = QRadioButton("IBIT")
        self.mode_playback_radio = QRadioButton("Flight Profile Playback")
        self.mode_ibit_radio.setChecked(True)
        self.mode_button_group = QButtonGroup()
        self.mode_button_group.addButton(self.mode_ibit_radio)
        self.mode_button_group.addButton(self.mode_playback_radio)
        mode_layout.addWidget(self.mode_ibit_radio)
        mode_layout.addWidget(self.mode_playback_radio)
        mode_layout.addStretch()
        mode_group.setLayout(mode_layout)
        layout.addWidget(mode_group, 1, 0, 1, 4)
        self.mode_ibit_radio.toggled.connect(self._on_mode_changed)

        # Playback sub-options (shown only in playback mode)
        self.playback_group = QGroupBox("Playback Options")
        playback_layout = QGridLayout()

        playback_layout.addWidget(QLabel("Profile CSV:"), 0, 0)
        self.playback_csv_input = QLineEdit()
        self.playback_csv_input.setReadOnly(True)
        self.playback_csv_input.setPlaceholderText("Select flight profile CSV...")
        playback_layout.addWidget(self.playback_csv_input, 0, 1)
        self.playback_csv_browse_btn = QPushButton("Browse")
        self.playback_csv_browse_btn.clicked.connect(self._browse_playback_csv)
        playback_layout.addWidget(self.playback_csv_browse_btn, 0, 2)

        playback_layout.addWidget(QLabel("Playback Type:"), 1, 0)
        self.playback_type_combo = QComboBox()
        self.playback_type_combo.addItems(["Actuation", "Propulsion", "Both"])
        playback_layout.addWidget(self.playback_type_combo, 1, 1)

        self.playback_group.setLayout(playback_layout)
        layout.addWidget(self.playback_group, 2, 0, 1, 4)
        self.playback_group.setVisible(False)

        # Skip state management
        self.skip_state_mgmt_checkbox = QCheckBox(
            "Skip State Management (faster, less safe)"
        )
        self.skip_state_mgmt_checkbox.setToolTip(
            "Skip capturing and restoring vehicle state"
        )
        layout.addWidget(self.skip_state_mgmt_checkbox, 3, 0, 1, 2)
        
        # Skip ARM requirement
        self.skip_arm_checkbox = QCheckBox(
            "Skip ARM requirement (test while disarmed)"
        )
        self.skip_arm_checkbox.setToolTip(
            "Run IBIT without arming - only works if vehicle permits"
        )
        layout.addWidget(self.skip_arm_checkbox, 4, 0, 1, 2)
        
        # Log directory
        layout.addWidget(QLabel("Log Directory:"), 5, 0)
        
        self.log_dir_input = QLineEdit()
        self.log_dir_input.setReadOnly(True)
        self.log_dir_input.setText(self.log_directory)
        layout.addWidget(self.log_dir_input, 5, 1, 1, 2)
        
        log_btn_layout = QHBoxLayout()
        
        self.log_dir_browse_btn = QPushButton("Browse")
        self.log_dir_browse_btn.clicked.connect(self.browse_clicked)
        log_btn_layout.addWidget(self.log_dir_browse_btn)
        
        self.open_log_dir_btn = QPushButton("Open")
        self.open_log_dir_btn.clicked.connect(self.open_clicked)
        log_btn_layout.addWidget(self.open_log_dir_btn)
        
        layout.addLayout(log_btn_layout, 5, 3)
        
        # Batch duration
        layout.addWidget(QLabel("Batch Duration:"), 6, 0)
        
        duration_layout = QHBoxLayout()
        
        self.duration_input = QSpinBox()
        self.duration_input.setRange(1, 99999)
        self.duration_input.setValue(14)
        duration_layout.addWidget(self.duration_input)
        
        self.duration_unit_combo = QComboBox()
        self.duration_unit_combo.addItems(["Seconds", "Minutes", "Hours", "Days"])
        self.duration_unit_combo.setCurrentText("Days")
        duration_layout.addWidget(self.duration_unit_combo)
        
        layout.addLayout(duration_layout, 6, 1)
        
        # Advanced settings group
        adv_group = QGroupBox("Advanced")
        adv_layout = QGridLayout()
        
        adv_layout.addWidget(QLabel("Connection Timeout:"), 0, 0)
        self.connection_timeout_input = QSpinBox()
        self.connection_timeout_input.setRange(1, 60)
        self.connection_timeout_input.setValue(10)
        self.connection_timeout_input.setSuffix(" s")
        adv_layout.addWidget(self.connection_timeout_input, 0, 1)
        
        adv_layout.addWidget(QLabel("Stabilization Delay:"), 1, 0)
        self.stabilization_delay_input = QSpinBox()
        self.stabilization_delay_input.setRange(0, 10)
        self.stabilization_delay_input.setValue(2)
        self.stabilization_delay_input.setSuffix(" s")
        adv_layout.addWidget(self.stabilization_delay_input, 1, 1)
        
        adv_layout.addWidget(QLabel("IBIT Timeout:"), 2, 0)
        self.ibit_timeout_input = QSpinBox()
        self.ibit_timeout_input.setRange(30, 600)
        self.ibit_timeout_input.setValue(300)
        self.ibit_timeout_input.setSuffix(" s")
        adv_layout.addWidget(self.ibit_timeout_input, 2, 1)
        
        adv_layout.addWidget(QLabel("Phase Timeout:"), 3, 0)
        self.phase_timeout_input = QSpinBox()
        self.phase_timeout_input.setRange(10, 300)
        self.phase_timeout_input.setValue(90)
        self.phase_timeout_input.setSuffix(" s")
        adv_layout.addWidget(self.phase_timeout_input, 3, 1)
        
        adv_layout.addWidget(QLabel("ARM Timeout:"), 4, 0)
        self.arm_timeout_input = QSpinBox()
        self.arm_timeout_input.setRange(10, 300)
        self.arm_timeout_input.setValue(60)
        self.arm_timeout_input.setSuffix(" s")
        adv_layout.addWidget(self.arm_timeout_input, 4, 1)
        
        adv_layout.addWidget(QLabel("Max ARM Iterations:"), 5, 0)
        self.max_arm_iterations_input = QSpinBox()
        self.max_arm_iterations_input.setRange(1, 100)
        self.max_arm_iterations_input.setValue(20)
        adv_layout.addWidget(self.max_arm_iterations_input, 5, 1)
        
        adv_group.setLayout(adv_layout)
        layout.addWidget(adv_group, 6, 2, 3, 2)
        
        self.setLayout(layout)
    
    def _on_mode_changed(self, ibit_selected):
        """Show/hide playback options based on mode selection"""
        self.playback_group.setVisible(not ibit_selected)
        self.mode_changed.emit('ibit' if ibit_selected else 'playback')

    def _browse_playback_csv(self):
        """Open file dialog to select playback CSV"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Flight Profile CSV",
            "",
            "CSV Files (*.csv)"
        )
        if file_path:
            self.playback_csv_input.setText(file_path)

    def get_test_mode(self):
        """Return 'ibit' or 'playback'"""
        return 'ibit' if self.mode_ibit_radio.isChecked() else 'playback'

    def get_playback_csv(self):
        """Return path to selected playback CSV"""
        return self.playback_csv_input.text()

    def get_playback_type(self):
        """Return 'Actuation', 'Propulsion', or 'Both'"""
        return self.playback_type_combo.currentText()

    def set_log_directory(self, directory):
        """Set log directory"""
        self.log_directory = directory
        self.log_dir_input.setText(directory)
        self.log_dir_changed.emit(directory)
    
    def get_duration(self):
        """
        Get test duration.
        
        Returns:
            tuple: (value, unit)
        """
        return self.duration_input.value(), self.duration_unit_combo.currentText()
    
    def get_connection_timeout(self):
        """Get connection timeout in seconds"""
        return self.connection_timeout_input.value()
    
    def get_stabilization_delay(self):
        """Get stabilization delay in seconds"""
        return self.stabilization_delay_input.value()
    
    def get_skip_state_management(self):
        """Get skip state management setting"""
        return self.skip_state_mgmt_checkbox.isChecked()
    
    def get_config(self):
        """
        Get complete configuration dictionary.
        
        Returns:
            dict: Configuration settings
        """
        return {
            'ibit_timeout': self.ibit_timeout_input.value(),
            'phase_timeout': self.phase_timeout_input.value(),
            'arm_timeout': self.arm_timeout_input.value(),
            'max_arm_iterations': self.max_arm_iterations_input.value(),
            'skip_arm_for_ibit': self.skip_arm_checkbox.isChecked(),
            'test_mode': self.get_test_mode(),
            'playback_csv': self.get_playback_csv(),
            'playback_type': self.get_playback_type(),
        }
    
    def get_all_settings(self):
        """Get all settings for saving"""
        return {
            'connection_timeout': self.connection_timeout_input.value(),
            'stabilization_delay': self.stabilization_delay_input.value(),
            'skip_state_management': self.skip_state_mgmt_checkbox.isChecked(),
            'skip_arm_for_ibit': self.skip_arm_checkbox.isChecked(),
            'ibit_timeout': self.ibit_timeout_input.value(),
            'phase_timeout': self.phase_timeout_input.value(),
            'arm_timeout': self.arm_timeout_input.value(),
            'max_arm_iterations': self.max_arm_iterations_input.value(),
            'test_mode': self.get_test_mode(),
            'playback_csv': self.get_playback_csv(),
            'playback_type': self.get_playback_type(),
        }
    
    def load_settings(self, settings):
        """Load settings from dictionary"""
        self.connection_timeout_input.setValue(
            settings.get('connection_timeout', 10)
        )
        self.stabilization_delay_input.setValue(
            settings.get('stabilization_delay', 2)
        )
        self.skip_state_mgmt_checkbox.setChecked(
            settings.get('skip_state_management', False)
        )
        self.skip_arm_checkbox.setChecked(
            settings.get('skip_arm_for_ibit', False)
        )
        self.ibit_timeout_input.setValue(
            settings.get('ibit_timeout', 300)
        )
        self.phase_timeout_input.setValue(
            settings.get('phase_timeout', 90)
        )
        self.arm_timeout_input.setValue(
            settings.get('arm_timeout', 60)
        )
        self.max_arm_iterations_input.setValue(
            settings.get('max_arm_iterations', 20)
        )
        if settings.get('test_mode', 'ibit') == 'playback':
            self.mode_playback_radio.setChecked(True)
        else:
            self.mode_ibit_radio.setChecked(True)
        if settings.get('playback_csv'):
            self.playback_csv_input.setText(settings['playback_csv'])
        if settings.get('playback_type'):
            idx = self.playback_type_combo.findText(settings['playback_type'])
            if idx >= 0:
                self.playback_type_combo.setCurrentIndex(idx)


# ============================================================
# UUT Table Widget
# ============================================================

class UUTTableWidget(QGroupBox):
    """
    UUT configuration table.
    
    Signals:
        add_clicked: Add button clicked
        edit_clicked: Edit button clicked
        remove_clicked: Remove button clicked
        save_clicked: Save config button clicked
        load_clicked: Load config button clicked
    """
    
    add_clicked = pyqtSignal()
    edit_clicked = pyqtSignal()
    remove_clicked = pyqtSignal()
    save_clicked = pyqtSignal()
    load_clicked = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__("UUT Configuration", parent)
        self.init_ui()
    
    def init_ui(self):
        """Initialize UI components"""
        layout = QVBoxLayout()
        
        # Button row
        button_layout = QHBoxLayout()
        
        self.add_btn = QPushButton("Add UUT")
        self.add_btn.clicked.connect(self.add_clicked)
        button_layout.addWidget(self.add_btn)
        
        self.edit_btn = QPushButton("Edit UUT")
        self.edit_btn.clicked.connect(self.edit_clicked)
        button_layout.addWidget(self.edit_btn)
        
        self.remove_btn = QPushButton("Remove UUT")
        self.remove_btn.clicked.connect(self.remove_clicked)
        button_layout.addWidget(self.remove_btn)
        
        self.save_btn = QPushButton("Save Config")
        self.save_btn.clicked.connect(self.save_clicked)
        button_layout.addWidget(self.save_btn)
        
        self.load_btn = QPushButton("Load Config")
        self.load_btn.clicked.connect(self.load_clicked)
        button_layout.addWidget(self.load_btn)
        
        button_layout.addStretch()
        
        layout.addLayout(button_layout)
        
        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            "#", "Serial Number", "IP Address", "Port", "Relay", "Status"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        layout.addWidget(self.table)
        
        self.setLayout(layout)
    
    def update_table(self, uuts):
        """
        Update table with UUT list.
        
        Args:
            uuts: List of UUT objects
        """
        self.table.setRowCount(len(uuts))
        
        for i, uut in enumerate(uuts):
            self.table.setItem(i, 0, QTableWidgetItem(str(i + 1)))
            self.table.setItem(i, 1, QTableWidgetItem(uut.serial_number))
            self.table.setItem(i, 2, QTableWidgetItem(uut.ip_address))
            self.table.setItem(i, 3, QTableWidgetItem(str(uut.port)))
            self.table.setItem(i, 4, QTableWidgetItem(f"D{uut.relay_line}"))
            
            status_item = QTableWidgetItem(uut.status)
            
            # Color code by status
            color = {
                "Ready": "#C8E6C9",
                "Testing": "#FFF9C4",
                "Complete": "#C8E6C9",
                "Failed": "#FFCDD2",
                "Failed (3x)": "#F44336",
                "Time Expired": "#D1C4E9",
                "Stopped": "#E0E0E0",
                "Retry": "#FFE0B2"
            }.get(uut.status, "#FFFFFF")
            
            status_item.setBackground(QColor(color))
            self.table.setItem(i, 5, status_item)
    
    def get_selected_row(self):
        """
        Get selected row index.
        
        Returns:
            int: Row index or -1 if none selected
        """
        selected = self.table.selectionModel().selectedRows()
        if not selected:
            return -1
        return selected[0].row()


# ============================================================
# Status Panel Widget
# ============================================================

class StatusPanelWidget(QGroupBox):
    """System status display panel"""
    
    def __init__(self, parent=None):
        super().__init__("System Status", parent)
        self.init_ui()
    
    def init_ui(self):
        """Initialize UI components"""
        layout = QGridLayout()
        
        # Connection status
        layout.addWidget(QLabel("Connection:"), 0, 0)
        
        self.connection_led = QLabel("●")
        self.connection_led.setStyleSheet("font-size: 24pt; color: gray;")
        layout.addWidget(self.connection_led, 0, 1)
        
        self.connection_label = QLabel("Not Connected")
        layout.addWidget(self.connection_label, 0, 2)
        
        # Armed status
        layout.addWidget(QLabel("Armed:"), 1, 0)
        
        self.armed_led = QLabel("●")
        self.armed_led.setStyleSheet("font-size: 24pt; color: gray;")
        layout.addWidget(self.armed_led, 1, 1)
        
        self.armed_label = QLabel("Unknown")
        layout.addWidget(self.armed_label, 1, 2)
        
        # Mode
        layout.addWidget(QLabel("Mode:"), 2, 0)
        
        self.mode_label = QLabel("---")
        self.mode_label.setStyleSheet(
            "background: gray; color: white; padding: 5px; "
            "border-radius: 3px; font-weight: bold;"
        )
        layout.addWidget(self.mode_label, 2, 1, 1, 2)
        
        self.setLayout(layout)
    
    def set_connection_health(self, is_healthy):
        """
        Set connection health indicator.
        
        Args:
            is_healthy: True if connection is healthy
        """
        if is_healthy:
            self.connection_led.setStyleSheet("font-size: 24pt; color: #4CAF50;")
            self.connection_label.setText("Connected")
            self.connection_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
        else:
            self.connection_led.setStyleSheet("font-size: 24pt; color: #f44336;")
            self.connection_label.setText("Connection Issue")
            self.connection_label.setStyleSheet("color: #f44336; font-weight: bold;")
    
    def set_armed_state(self, armed, flight_regime):
        """
        Set armed state display.
        
        Args:
            armed: True if armed
            flight_regime: Flight regime number
        """
        regime_names = {
            0: "GROUND_DISARMED", 1: "GROUND_ARMED", 2: "AUTO_TAKEOFF",
            3: "HOVER", 4: "FORWARD_TRANSITION", 5: "CRUISE",
            6: "IN_AIR_RESTART", 7: "BACK_TRANSITION", 8: "EXTERNAL_GUIDANCE",
            9: "TAKEOFF_ABORTED", 10: "POWERING_OFF", 11: "CUT_POWER",
            12: "TERMINATE", 13: "SCUTTLE", 14: "NULL_ATTITUDE_AND_COLLECTIVE",
            15: "NULL_ATTITUDE_FIXED_COLLECTIVE", 16: "LANDNOW_OL", 17: "LANDNOW_CL",
            18: "PILOT_OVERRIDE", 19: "EMERGENCY_STOP", 20: "AUTO_RECOVERY",
            21: "WAVE_OFF", 22: "TAXI", 255: "INVALID"
        }
        regime_str = regime_names.get(flight_regime, f"REGIME_{flight_regime}")
        
        if armed:
            self.armed_led.setStyleSheet("font-size: 24pt; color: #FF5722;")
            self.armed_label.setText(f"ARMED ({regime_str})")
            self.armed_label.setStyleSheet("color: #FF5722; font-weight: bold;")
        else:
            self.armed_led.setStyleSheet("font-size: 24pt; color: #4CAF50;")
            self.armed_label.setText(f"Disarmed ({regime_str})")
            self.armed_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
    
    def set_mode(self, mode):
        """
        Set actuation mode display.
        
        Args:
            mode: Mode number (0-5)
        """
        mode_names = {
            0: "OFF",
            1: "IBIT",
            2: "OPERATE",
            3: "MANUAL",
            4: "PLAYBACK",
            5: "TRIM"
        }
        mode_colors = {
            0: "#757575",
            1: "#FF9800",
            2: "#4CAF50",
            3: "#2196F3",
            4: "#9C27B0",
            5: "#00BCD4"
        }
        
        mode_str = mode_names.get(mode, f"UNKNOWN({mode})")
        mode_color = mode_colors.get(mode, "#757575")
        
        self.mode_label.setText(mode_str)
        self.mode_label.setStyleSheet(
            f"background: {mode_color}; color: white; padding: 5px; "
            f"border-radius: 3px; font-weight: bold;"
        )
    
    def reset(self):
        """Reset to default state"""
        self.connection_led.setStyleSheet("font-size: 24pt; color: gray;")
        self.connection_label.setText("Not Connected")
        self.connection_label.setStyleSheet("color: gray;")
        
        self.armed_led.setStyleSheet("font-size: 24pt; color: gray;")
        self.armed_label.setText("Unknown")
        self.armed_label.setStyleSheet("color: gray;")
        
        self.mode_label.setText("---")
        self.mode_label.setStyleSheet(
            "background: gray; color: white; padding: 5px; "
            "border-radius: 3px; font-weight: bold;"
        )


# ============================================================
# IBIT Display Widget
# ============================================================

class IBITDisplayWidget(QGroupBox):
    """IBIT / Playback status display — adapts to current test mode"""
    
    def __init__(self, parent=None):
        super().__init__("Test Status", parent)
        self.init_ui()
    
    def init_ui(self):
        """Initialize UI components"""
        layout = QGridLayout()
        
        # --- Row 0: primary state label (IBIT substate OR Playback frame %) ---
        layout.addWidget(QLabel("State:"), 0, 0)
        self.substate_label = QLabel("---")
        self.substate_label.setStyleSheet(
            "font-family: monospace; font-size: 12pt; font-weight: bold; "
            "background: #E0E0E0; padding: 8px; border-radius: 4px;"
        )
        layout.addWidget(self.substate_label, 0, 1, 1, 2)

        # --- Row 1: hint line (changes per mode) ---
        self.hint_label = QLabel("0:BEGIN 1:SETTLE 2:ELEVON 3:RUDDER 4:TVC 5:DONE")
        self.hint_label.setStyleSheet("font-size: 8pt; color: #666;")
        layout.addWidget(self.hint_label, 1, 0, 1, 3)

        # --- Row 2: mistracking indicator (playback only, hidden in IBIT) ---
        self._mistracking_title = QLabel("Mistracking:")
        layout.addWidget(self._mistracking_title, 2, 0)
        self.mistracking_label = QLabel("None")
        self.mistracking_label.setStyleSheet(
            "font-family: monospace; font-size: 10pt; font-weight: bold; "
            "background: #4CAF50; color: white; padding: 5px; border-radius: 4px;"
        )
        layout.addWidget(self.mistracking_label, 2, 1, 1, 2)
        # Hidden by default — shown only in playback mode
        self._mistracking_title.setVisible(False)
        self.mistracking_label.setVisible(False)
        self._mistracking_row_widgets = [
            self._mistracking_title,
            self.mistracking_label
        ]

        # --- Row 3: test duration ---
        layout.addWidget(QLabel("Test Duration:"), 3, 0)
        self.duration_label = QLabel("0.0 s")
        self.duration_label.setStyleSheet("font-family: monospace; font-size: 10pt;")
        layout.addWidget(self.duration_label, 3, 1)

        self.setLayout(layout)
        self._mode = 'ibit'

    def set_mode(self, mode):
        """
        Switch display between 'ibit' and 'playback' modes.

        Args:
            mode: 'ibit' or 'playback'
        """
        self._mode = mode
        is_playback = (mode == 'playback')

        if is_playback:
            self.setTitle("Playback Status")
            self.hint_label.setText(
                "Streaming flight profile at 100 Hz — progress shown as %"
            )
            for w in self._mistracking_row_widgets:
                w.setVisible(True)
            self.reset()
        else:
            self.setTitle("IBIT Status")
            self.hint_label.setText(
                "0:BEGIN 1:SETTLE 2:ELEVON 3:RUDDER 4:TVC 5:DONE"
            )
            for w in self._mistracking_row_widgets:
                w.setVisible(False)
            self.reset()

    def set_substate(self, substate_name):
        """
        Set IBIT substate display.

        Args:
            substate_name: Name of current substate
        """
        self.substate_label.setText(substate_name)
        colors = {
            "BEGIN": "#2196F3",
            "WAIT_FOR_SETTLE": "#FF9800",
            "ELEVONS": "#FF9800",
            "RUDDERS": "#FF9800",
            "TVC": "#FF9800",
            "✓ COMPLETE": "#4CAF50"
        }
        color = colors.get(substate_name, "#E0E0E0")
        text_color = "white" if color != "#E0E0E0" else "#333"
        self.substate_label.setStyleSheet(
            f"font-family: monospace; font-size: 12pt; font-weight: bold; "
            f"background: {color}; color: {text_color}; "
            f"padding: 8px; border-radius: 4px;"
        )

    def set_playback_progress(self, percent):
        """
        Update playback frame progress display.

        Args:
            percent: 0-100
        """
        self.substate_label.setText(f"Streaming... {percent}%")
        # Gradient from blue (0%) to green (100%)
        if percent >= 100:
            color = "#4CAF50"
        elif percent >= 50:
            color = "#FF9800"
        else:
            color = "#2196F3"
        self.substate_label.setStyleSheet(
            f"font-family: monospace; font-size: 12pt; font-weight: bold; "
            f"background: {color}; color: white; padding: 8px; border-radius: 4px;"
        )

    def set_mistracking(self, flags, flag_names):
        """
        Update mistracking indicator for playback mode.

        Args:
            flags: int — accumulated PANDION_RR_IBIT_MON_STATUS_FLAGS bitmask
            flag_names: list of str — names of set flags (empty if none)
        """
        if flags == 0:
            self.mistracking_label.setText("None")
            self.mistracking_label.setStyleSheet(
                "font-family: monospace; font-size: 10pt; font-weight: bold; "
                "background: #4CAF50; color: white; padding: 5px; border-radius: 4px;"
            )
        else:
            self.mistracking_label.setText(", ".join(flag_names))
            self.mistracking_label.setStyleSheet(
                "font-family: monospace; font-size: 10pt; font-weight: bold; "
                "background: #f44336; color: white; padding: 5px; border-radius: 4px;"
            )

    def set_duration(self, duration):
        """
        Set test duration display.

        Args:
            duration: Duration in seconds
        """
        self.duration_label.setText(f"{duration:.1f} s")

    def reset(self):
        """Reset to default state"""
        self.substate_label.setText("---")
        self.substate_label.setStyleSheet(
            "font-family: monospace; font-size: 12pt; font-weight: bold; "
            "background: #E0E0E0; padding: 8px; border-radius: 4px;"
        )
        self.duration_label.setText("0.0 s")
        self.mistracking_label.setText("None")
        self.mistracking_label.setStyleSheet(
            "font-family: monospace; font-size: 10pt; font-weight: bold; "
            "background: #4CAF50; color: white; padding: 5px; border-radius: 4px;"
        )


# ============================================================
# Actuator Feedback Widget
# ============================================================

class ActuatorFeedbackWidget(QGroupBox):
    """Actuator feedback display panel"""
    
    def __init__(self, parent=None):
        super().__init__("Actuator Feedback", parent)
        self.init_ui()
    
    def init_ui(self):
        """Initialize UI components"""
        layout = QGridLayout()
        layout.setSpacing(3)
        
        # Header row
        layout.addWidget(QLabel("<b>Actuator</b>"), 0, 0)
        layout.addWidget(QLabel("<b>Command (°)</b>"), 0, 1)
        layout.addWidget(QLabel("<b>Feedback (°)</b>"), 0, 2)
        layout.addWidget(QLabel("<b>Delta (°)</b>"), 0, 3)
        layout.addWidget(QLabel("<b>Current (mA)</b>"), 0, 4)
        layout.addWidget(QLabel("<b>Temp (°C)</b>"), 0, 5)
        
        # Left Elevon
        layout.addWidget(QLabel("Left Elevon:"), 1, 0)
        self.left_elevon_cmd_label    = QLabel("---"); self.left_elevon_cmd_label.setStyleSheet("font-family: monospace;"); layout.addWidget(self.left_elevon_cmd_label, 1, 1)
        self.left_elevon_pos_label    = QLabel("---"); self.left_elevon_pos_label.setStyleSheet("font-family: monospace;"); layout.addWidget(self.left_elevon_pos_label, 1, 2)
        self.left_elevon_delta_label  = QLabel("---"); self.left_elevon_delta_label.setStyleSheet("font-family: monospace;"); layout.addWidget(self.left_elevon_delta_label, 1, 3)
        self.left_elevon_curr_label   = QLabel("---"); self.left_elevon_curr_label.setStyleSheet("font-family: monospace;"); layout.addWidget(self.left_elevon_curr_label, 1, 4)
        self.left_elevon_temp_label   = QLabel("---"); self.left_elevon_temp_label.setStyleSheet("font-family: monospace;"); layout.addWidget(self.left_elevon_temp_label, 1, 5)

        # Right Elevon
        layout.addWidget(QLabel("Right Elevon:"), 2, 0)
        self.right_elevon_cmd_label   = QLabel("---"); self.right_elevon_cmd_label.setStyleSheet("font-family: monospace;"); layout.addWidget(self.right_elevon_cmd_label, 2, 1)
        self.right_elevon_pos_label   = QLabel("---"); self.right_elevon_pos_label.setStyleSheet("font-family: monospace;"); layout.addWidget(self.right_elevon_pos_label, 2, 2)
        self.right_elevon_delta_label = QLabel("---"); self.right_elevon_delta_label.setStyleSheet("font-family: monospace;"); layout.addWidget(self.right_elevon_delta_label, 2, 3)
        self.right_elevon_curr_label  = QLabel("---"); self.right_elevon_curr_label.setStyleSheet("font-family: monospace;"); layout.addWidget(self.right_elevon_curr_label, 2, 4)
        self.right_elevon_temp_label  = QLabel("---"); self.right_elevon_temp_label.setStyleSheet("font-family: monospace;"); layout.addWidget(self.right_elevon_temp_label, 2, 5)

        # Dorsal Rudder
        layout.addWidget(QLabel("Dorsal Rudder:"), 3, 0)
        self.dorsal_rudder_cmd_label    = QLabel("---"); self.dorsal_rudder_cmd_label.setStyleSheet("font-family: monospace;"); layout.addWidget(self.dorsal_rudder_cmd_label, 3, 1)
        self.dorsal_rudder_pos_label    = QLabel("---"); self.dorsal_rudder_pos_label.setStyleSheet("font-family: monospace;"); layout.addWidget(self.dorsal_rudder_pos_label, 3, 2)
        self.dorsal_rudder_delta_label  = QLabel("---"); self.dorsal_rudder_delta_label.setStyleSheet("font-family: monospace;"); layout.addWidget(self.dorsal_rudder_delta_label, 3, 3)
        self.dorsal_rudder_curr_label   = QLabel("---"); self.dorsal_rudder_curr_label.setStyleSheet("font-family: monospace;"); layout.addWidget(self.dorsal_rudder_curr_label, 3, 4)
        layout.addWidget(QLabel("N/A"), 3, 5)

        # Ventral Rudder
        layout.addWidget(QLabel("Ventral Rudder:"), 4, 0)
        self.ventral_rudder_cmd_label   = QLabel("---"); self.ventral_rudder_cmd_label.setStyleSheet("font-family: monospace;"); layout.addWidget(self.ventral_rudder_cmd_label, 4, 1)
        self.ventral_rudder_pos_label   = QLabel("---"); self.ventral_rudder_pos_label.setStyleSheet("font-family: monospace;"); layout.addWidget(self.ventral_rudder_pos_label, 4, 2)
        self.ventral_rudder_delta_label = QLabel("---"); self.ventral_rudder_delta_label.setStyleSheet("font-family: monospace;"); layout.addWidget(self.ventral_rudder_delta_label, 4, 3)
        self.ventral_rudder_curr_label  = QLabel("---"); self.ventral_rudder_curr_label.setStyleSheet("font-family: monospace;"); layout.addWidget(self.ventral_rudder_curr_label, 4, 4)
        layout.addWidget(QLabel("N/A"), 4, 5)

        # Left TVC Upper
        layout.addWidget(QLabel("Left TVC Upper:"), 5, 0)
        self.left_tvc_upper_cmd_label   = QLabel("---"); self.left_tvc_upper_cmd_label.setStyleSheet("font-family: monospace;"); layout.addWidget(self.left_tvc_upper_cmd_label, 5, 1)
        self.left_tvc_upper_pos_label   = QLabel("---"); self.left_tvc_upper_pos_label.setStyleSheet("font-family: monospace;"); layout.addWidget(self.left_tvc_upper_pos_label, 5, 2)
        self.left_tvc_upper_delta_label = QLabel("---"); self.left_tvc_upper_delta_label.setStyleSheet("font-family: monospace;"); layout.addWidget(self.left_tvc_upper_delta_label, 5, 3)
        self.left_tvc_upper_curr_label  = QLabel("---"); self.left_tvc_upper_curr_label.setStyleSheet("font-family: monospace;"); layout.addWidget(self.left_tvc_upper_curr_label, 5, 4)
        layout.addWidget(QLabel("N/A"), 5, 5)

        # Left TVC Lower
        layout.addWidget(QLabel("Left TVC Lower:"), 6, 0)
        self.left_tvc_lower_cmd_label   = QLabel("---"); self.left_tvc_lower_cmd_label.setStyleSheet("font-family: monospace;"); layout.addWidget(self.left_tvc_lower_cmd_label, 6, 1)
        self.left_tvc_lower_pos_label   = QLabel("---"); self.left_tvc_lower_pos_label.setStyleSheet("font-family: monospace;"); layout.addWidget(self.left_tvc_lower_pos_label, 6, 2)
        self.left_tvc_lower_delta_label = QLabel("---"); self.left_tvc_lower_delta_label.setStyleSheet("font-family: monospace;"); layout.addWidget(self.left_tvc_lower_delta_label, 6, 3)
        self.left_tvc_lower_curr_label  = QLabel("---"); self.left_tvc_lower_curr_label.setStyleSheet("font-family: monospace;"); layout.addWidget(self.left_tvc_lower_curr_label, 6, 4)
        layout.addWidget(QLabel("N/A"), 6, 5)

        # Right TVC Upper
        layout.addWidget(QLabel("Right TVC Upper:"), 7, 0)
        self.right_tvc_upper_cmd_label   = QLabel("---"); self.right_tvc_upper_cmd_label.setStyleSheet("font-family: monospace;"); layout.addWidget(self.right_tvc_upper_cmd_label, 7, 1)
        self.right_tvc_upper_pos_label   = QLabel("---"); self.right_tvc_upper_pos_label.setStyleSheet("font-family: monospace;"); layout.addWidget(self.right_tvc_upper_pos_label, 7, 2)
        self.right_tvc_upper_delta_label = QLabel("---"); self.right_tvc_upper_delta_label.setStyleSheet("font-family: monospace;"); layout.addWidget(self.right_tvc_upper_delta_label, 7, 3)
        self.right_tvc_upper_curr_label  = QLabel("---"); self.right_tvc_upper_curr_label.setStyleSheet("font-family: monospace;"); layout.addWidget(self.right_tvc_upper_curr_label, 7, 4)
        layout.addWidget(QLabel("N/A"), 7, 5)

        # Right TVC Lower
        layout.addWidget(QLabel("Right TVC Lower:"), 8, 0)
        self.right_tvc_lower_cmd_label   = QLabel("---"); self.right_tvc_lower_cmd_label.setStyleSheet("font-family: monospace;"); layout.addWidget(self.right_tvc_lower_cmd_label, 8, 1)
        self.right_tvc_lower_pos_label   = QLabel("---"); self.right_tvc_lower_pos_label.setStyleSheet("font-family: monospace;"); layout.addWidget(self.right_tvc_lower_pos_label, 8, 2)
        self.right_tvc_lower_delta_label = QLabel("---"); self.right_tvc_lower_delta_label.setStyleSheet("font-family: monospace;"); layout.addWidget(self.right_tvc_lower_delta_label, 8, 3)
        self.right_tvc_lower_curr_label  = QLabel("---"); self.right_tvc_lower_curr_label.setStyleSheet("font-family: monospace;"); layout.addWidget(self.right_tvc_lower_curr_label, 8, 4)
        layout.addWidget(QLabel("N/A"), 8, 5)

        # Last update timestamp
        self.last_update_label = QLabel("Last Update: Never")
        self.last_update_label.setStyleSheet("color: #666; font-size: 8pt;")
        layout.addWidget(self.last_update_label, 9, 0, 1, 6)

        self.setLayout(layout)

    def _delta_style(self, delta_deg):
        """Color-code delta: green < 0.5°, amber 0.5–1°, red > 1°"""
        if delta_deg < 0.5:
            return "font-family: monospace; color: #4CAF50;"
        elif delta_deg < 1.0:
            return "font-family: monospace; color: #FF9800;"
        else:
            return "font-family: monospace; font-weight: bold; color: #f44336;"

    def update_feedback(self, actuator_data):
        """
        Update actuator feedback displays.

        actuator_data may optionally contain command fields
        (present during playback, absent during IBIT):
          left_elevon_cmd_cdeg, right_elevon_cmd_cdeg, etc.

        Args:
            actuator_data: Dictionary with actuator feedback (and optionally command) data
        """
        try:
            surfaces = [
                ('left_elevon',    'left_elevon_cmd_label',    'left_elevon_pos_label',    'left_elevon_delta_label',    'left_elevon_curr_label',    'left_elevon_temp_label'),
                ('right_elevon',   'right_elevon_cmd_label',   'right_elevon_pos_label',   'right_elevon_delta_label',   'right_elevon_curr_label',   'right_elevon_temp_label'),
                ('dorsal_rudder',  'dorsal_rudder_cmd_label',  'dorsal_rudder_pos_label',  'dorsal_rudder_delta_label',  'dorsal_rudder_curr_label',  None),
                ('ventral_rudder', 'ventral_rudder_cmd_label', 'ventral_rudder_pos_label', 'ventral_rudder_delta_label', 'ventral_rudder_curr_label', None),
                ('left_tvc_upper', 'left_tvc_upper_cmd_label', 'left_tvc_upper_pos_label', 'left_tvc_upper_delta_label', 'left_tvc_upper_curr_label', None),
                ('left_tvc_lower', 'left_tvc_lower_cmd_label', 'left_tvc_lower_pos_label', 'left_tvc_lower_delta_label', 'left_tvc_lower_curr_label', None),
                ('right_tvc_upper','right_tvc_upper_cmd_label','right_tvc_upper_pos_label','right_tvc_upper_delta_label','right_tvc_upper_curr_label',None),
                ('right_tvc_lower','right_tvc_lower_cmd_label','right_tvc_lower_pos_label','right_tvc_lower_delta_label','right_tvc_lower_curr_label',None),
            ]

            for name, cmd_attr, fb_attr, delta_attr, curr_attr, temp_attr in surfaces:
                fb_cdeg = actuator_data.get(f'{name}_feedback_cdeg')
                cmd_cdeg = actuator_data.get(f'{name}_cmd_cdeg')
                curr = actuator_data.get(f'{name}_current_mA')

                fb_deg = fb_cdeg / 100.0 if fb_cdeg is not None else None
                cmd_deg = cmd_cdeg / 100.0 if cmd_cdeg is not None else None

                # Command
                getattr(self, cmd_attr).setText(
                    f"{cmd_deg:.1f}" if cmd_deg is not None else "---"
                )
                # Feedback
                getattr(self, fb_attr).setText(
                    f"{fb_deg:.1f}" if fb_deg is not None else "---"
                )
                # Delta
                delta_label = getattr(self, delta_attr)
                if cmd_deg is not None and fb_deg is not None:
                    delta = abs(cmd_deg - fb_deg)
                    delta_label.setText(f"{delta:.1f}")
                    delta_label.setStyleSheet(self._delta_style(delta))
                else:
                    delta_label.setText("---")
                    delta_label.setStyleSheet("font-family: monospace;")
                # Current
                if curr_attr:
                    getattr(self, curr_attr).setText(
                        str(curr) if curr is not None else "---"
                    )
                # Temp
                if temp_attr:
                    temp = actuator_data.get(f'{name}_motor_temp_degC')
                    getattr(self, temp_attr).setText(
                        str(temp) if temp is not None else "---"
                    )

            self.last_update_label.setText(
                f"Last Update: {datetime.now().strftime('%H:%M:%S')}"
            )
        except Exception:
            pass

    def reset(self):
        """Reset to default state"""
        all_labels = [
            attr for attr in dir(self)
            if attr.endswith(('_cmd_label', '_pos_label', '_delta_label',
                              '_curr_label', '_temp_label'))
            and isinstance(getattr(self, attr), QLabel)
        ]
        for attr in all_labels:
            lbl = getattr(self, attr)
            lbl.setText("---")
            lbl.setStyleSheet("font-family: monospace;")
        self.last_update_label.setText("Last Update: Never")


# ============================================================
# Alert Banner Widget
# ============================================================

class AlertBannerWidget(QLabel):
    """Alert banner for important messages"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            "background: #FF5722; color: white; "
            "font-size: 12pt; padding: 10px; font-weight: bold; "
            "border-radius: 5px;"
        )
        self.setAlignment(Qt.AlignCenter)
        self.setVisible(False)
        self.setWordWrap(True)
        
        # Auto-hide timer
        self.hide_timer = QTimer()
        self.hide_timer.timeout.connect(self.hide)
        self.hide_timer.setSingleShot(True)
    
    def show_alert(self, message, auto_hide_ms=10000):
        """
        Show alert message.
        
        Args:
            message: Alert message
            auto_hide_ms: Auto-hide after this many milliseconds (0 = no auto-hide)
        """
        self.setText(f"⚠ {message}")
        self.setVisible(True)
        
        if auto_hide_ms > 0:
            self.hide_timer.start(auto_hide_ms)


# ============================================================
# Progress Widget
# ============================================================

class ProgressWidget(QGroupBox):
    """Current test progress display"""
    
    def __init__(self, parent=None):
        super().__init__("Current Test Progress", parent)
        self.init_ui()
    
    def init_ui(self):
        """Initialize UI components"""
        layout = QVBoxLayout()
        
        # Info grid
        info_layout = QGridLayout()
        
        info_layout.addWidget(QLabel("Testing:"), 0, 0)
        self.current_uut_label = QLabel("---")
        self.current_uut_label.setStyleSheet("font-weight: bold; font-size: 11pt;")
        info_layout.addWidget(self.current_uut_label, 0, 1)

        self._iteration_title_label = QLabel("Iteration:")
        info_layout.addWidget(self._iteration_title_label, 1, 0)
        self.iteration_label = QLabel("0")
        self.iteration_label.setStyleSheet("font-weight: bold;")
        info_layout.addWidget(self.iteration_label, 1, 1)
        
        info_layout.addWidget(QLabel("Batch Elapsed:"), 0, 2)
        self.elapsed_label = QLabel("00:00:00")
        self.elapsed_label.setStyleSheet("font-weight: bold; font-family: monospace;")
        info_layout.addWidget(self.elapsed_label, 0, 3)
        
        info_layout.addWidget(QLabel("Batch Remaining:"), 1, 2)
        self.remaining_label = QLabel("00:00:00")
        self.remaining_label.setStyleSheet("font-weight: bold; font-family: monospace;")
        info_layout.addWidget(self.remaining_label, 1, 3)
        
        layout.addLayout(info_layout)
        
        # Progress bar
        progress_layout = QVBoxLayout()
        progress_layout.addWidget(QLabel("Batch Progress:"))
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        progress_layout.addWidget(self.progress_bar)
        
        layout.addLayout(progress_layout)
        
        self.setLayout(layout)
    
    def set_current_uut(self, text):
        """Set current UUT label"""
        self.current_uut_label.setText(text)

    def set_test_mode(self, mode):
        """Update iteration label title for current mode"""
        self._iteration_title_label.setText(
            "Iteration:" if mode == 'ibit' else "Frame:"
        )

    def set_iteration(self, iteration):
        """Set iteration number"""
        self.iteration_label.setText(str(iteration))
    
    def set_elapsed(self, seconds):
        """Set elapsed time"""
        self.elapsed_label.setText(time.strftime('%H:%M:%S', time.gmtime(seconds)))
    
    def set_remaining(self, seconds):
        """Set remaining time"""
        self.remaining_label.setText(time.strftime('%H:%M:%S', time.gmtime(seconds)))
    
    def set_progress(self, percent):
        """Set progress bar percentage"""
        self.progress_bar.setValue(percent)


# ============================================================
# Control Buttons Widget
# ============================================================

class ControlButtonsWidget(QWidget):
    """Test control buttons"""
    
    start_clicked = pyqtSignal()
    stop_clicked = pyqtSignal()
    emergency_clicked = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()
    
    def init_ui(self):
        """Initialize UI components"""
        layout = QHBoxLayout()
        
        self.start_btn = QPushButton("▶ Start IBIT Test")
        self.start_btn.setStyleSheet(
            "background-color: #4CAF50; font-weight: bold; "
            "min-height: 50px; font-size: 14pt;"
        )
        self.start_btn.clicked.connect(self.start_clicked)
        layout.addWidget(self.start_btn)
        
        self.stop_btn = QPushButton("⏹ Stop")
        self.stop_btn.setStyleSheet(
            "background-color: #f44336; font-weight: bold; "
            "min-height: 50px; font-size: 14pt;"
        )
        self.stop_btn.clicked.connect(self.stop_clicked)
        self.stop_btn.setEnabled(False)
        layout.addWidget(self.stop_btn)
        
        self.emergency_btn = QPushButton("⚠ EMERGENCY STOP")
        self.emergency_btn.setStyleSheet(
            "background-color: #C62828; color: white; font-weight: bold; "
            "min-height: 50px; font-size: 14pt;"
        )
        self.emergency_btn.clicked.connect(self.emergency_clicked)
        layout.addWidget(self.emergency_btn)
        
        self.setLayout(layout)
    
    def set_testing_mode(self, testing):
        """
        Set buttons for testing or idle mode.
        
        Args:
            testing: True if testing is active
        """
        self.start_btn.setEnabled(not testing)
        self.stop_btn.setEnabled(testing)
    
    def set_test_mode_label(self, mode):
        """
        Update start button label to reflect selected test mode.

        Args:
            mode: 'ibit' or 'playback'
        """
        if mode == 'playback':
            self.start_btn.setText("▶ Start Playback Test")
        else:
            self.start_btn.setText("▶ Start IBIT Test")

    def set_enabled(self, start_enabled, stop_enabled):
        """Set individual button states"""
        self.start_btn.setEnabled(start_enabled)
        self.stop_btn.setEnabled(stop_enabled)


# ============================================================
# Log Widget
# ============================================================

class LogWidget(QGroupBox):
    """Test log display"""
    
    def __init__(self, parent=None):
        super().__init__("Test Log", parent)
        self.init_ui()
    
    def init_ui(self):
        """Initialize UI components"""
        layout = QVBoxLayout()
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(200)
        self.log_text.setMaximumHeight(400)
        self.log_text.setStyleSheet("font-family: monospace; font-size: 9pt;")
        layout.addWidget(self.log_text)
        
        clear_btn = QPushButton("Clear Log")
        clear_btn.clicked.connect(self.log_text.clear)
        layout.addWidget(clear_btn, 0, Qt.AlignRight)
        
        self.setLayout(layout)
    
    def append(self, message):
        """
        Append message to log.
        
        Args:
            message: Log message
        """
        timestamp = time.strftime('%H:%M:%S')
        self.log_text.append(f"[{timestamp}] {message}")
        
        # Auto-scroll to bottom
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())


# ============================================================
# Add/Edit UUT Dialog
# ============================================================

class AddUUTDialog(QDialog):
    """Dialog for adding/editing UUT configuration"""
    
    def __init__(self, parent=None, uut=None):
        super().__init__(parent)
        self.uut = uut
        self.init_ui()
        
        if uut:
            self.load_uut_data()
    
    def init_ui(self):
        """Initialize UI components"""
        self.setWindowTitle("Add/Edit UUT")
        self.setModal(True)
        
        layout = QVBoxLayout()
        
        # Form layout
        form_layout = QGridLayout()
        
        form_layout.addWidget(QLabel("Serial Number:"), 0, 0)
        self.serial_input = QLineEdit()
        form_layout.addWidget(self.serial_input, 0, 1)
        
        form_layout.addWidget(QLabel("IP Address:"), 1, 0)
        self.ip_input = QLineEdit()
        self.ip_input.setPlaceholderText("192.168.1.100")
        form_layout.addWidget(self.ip_input, 1, 1)
        
        form_layout.addWidget(QLabel("Port:"), 2, 0)
        self.port_input = QSpinBox()
        self.port_input.setRange(1, 65535)
        self.port_input.setValue(9985)
        form_layout.addWidget(self.port_input, 2, 1)
        
        form_layout.addWidget(QLabel("Relay Line:"), 3, 0)
        self.relay_input = QSpinBox()
        self.relay_input.setRange(0, 7)
        self.relay_input.setValue(0)
        form_layout.addWidget(self.relay_input, 3, 1)
        
        layout.addLayout(form_layout)
        
        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
        self.setLayout(layout)
    
    def load_uut_data(self):
        """Load existing UUT data into form"""
        self.serial_input.setText(self.uut.serial_number)
        self.ip_input.setText(self.uut.ip_address)
        self.port_input.setValue(self.uut.port)
        self.relay_input.setValue(self.uut.relay_line)
    
    def get_uut(self):
        """
        Get UUT object from form.
        
        Returns:
            UUT object
        """
        from vehicle.connection import UUT
        return UUT(
            serial_number=self.serial_input.text(),
            ip_address=self.ip_input.text(),
            port=self.port_input.value(),
            relay_line=self.relay_input.value()
        )