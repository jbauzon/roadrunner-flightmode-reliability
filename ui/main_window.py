"""
Main Window - Roadrunner Flight Test operator console.
"""
import os
import json
import time
import socket
import threading
import platform
import subprocess
from datetime import datetime

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QMessageBox, QFileDialog, QApplication, QScrollArea, QSizePolicy
)
from PyQt5.QtCore import QTimer, Qt, pyqtSignal
from PyQt5.QtGui import QFont

from hardware.daq import SimpleDAQController
from vehicle.connection import UUT
from testing.executor import UUTTestExecutor, PlaybackTestExecutor
from . import theme as T
from .widgets import (
    HeaderBanner,
    DAQSetupWidget, TestConfigWidget, UUTTableWidget,
    StatusPanelWidget, IBITDisplayWidget, ActuatorFeedbackWidget,
    AlertBannerWidget, ProgressWidget, ControlButtonsWidget,
    LogWidget, AddUUTDialog
)


class MultiUUTTestGUI(QMainWindow):
    """Roadrunner Flight Test operator console — multi-UUT IBIT and Playback."""

    # Signal for executing commands from the command server thread
    _remote_cmd = pyqtSignal(str, dict)

    COMMAND_PORT = 18888

    def __init__(self):
        super().__init__()

        # Remote command signal -> handler on GUI thread
        self._remote_cmd.connect(self._execute_remote_command)
        self._cmd_response = {}
        self._cmd_event = threading.Event()

        # ── Directories ───────────────────────────────────────────────────
        # script_dir is ui/ — project root is one level up
        self.script_dir    = os.path.dirname(os.path.abspath(__file__))
        self.project_root  = os.path.abspath(os.path.join(self.script_dir, ".."))
        self.log_directory = os.path.abspath(os.path.join(self.project_root, "logs"))
        self.report_directory = os.path.abspath(os.path.join(self.project_root, "reports"))
        os.makedirs(self.log_directory, exist_ok=True)
        os.makedirs(self.report_directory, exist_ok=True)

        # ── Hardware ──────────────────────────────────────────────────────
        self.daq = SimpleDAQController()

        # ── State ─────────────────────────────────────────────────────────
        self.uuts                  = []
        self.current_test_executor = None
        self.current_uut_index     = -1
        self.batch_start_datetime  = None
        self.batch_end_time        = None
        self.testing_active        = False
        self.current_statistics    = None
        self.test_mode             = 'ibit'
        self.playback_csv          = ''
        self.playback_type         = 'Actuation'

        self.test_config = {
            'ibit_timeout':       300.0,
            'phase_timeout':       90.0,
            'arm_timeout':         60.0,
            'max_arm_iterations':  20,
            'skip_arm_for_ibit':   False,
        }

        # ── Timers ────────────────────────────────────────────────────────
        self.daq_health_timer = QTimer()
        self.elapsed_timer    = QTimer()

        # ── Build UI ──────────────────────────────────────────────────────
        self._init_ui()

        # ── Post-build wiring ─────────────────────────────────────────────
        self.daq_health_timer.timeout.connect(self.check_daq_health)
        self.daq_health_timer.start(60_000)

        QTimer.singleShot(100, self.load_settings)
        QTimer.singleShot(500, self.detect_daq_devices)
        QTimer.singleShot(200, lambda: self.on_test_mode_changed(
            self.test_config_widget.get_test_mode()
        ))

        # Start command server for remote control (click_start.py, test scripts)
        self._start_command_server()

    # ═══════════════════════════════════════════════════════════════════════
    # UI construction
    # ═══════════════════════════════════════════════════════════════════════

    def _init_ui(self):
        self.setWindowTitle("Roadrunner Flight Test  —  IBIT")
        self.setMinimumSize(1400, 820)
        self.resize(1800, 1000)

        # ── Root ──────────────────────────────────────────────────────────
        root = QWidget()
        self.setCentralWidget(root)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Header banner
        self.header = HeaderBanner()
        root_layout.addWidget(self.header)

        # Alert banner (hidden until needed)
        self.alert_banner = AlertBannerWidget()
        root_layout.addWidget(self.alert_banner)

        # ── Main content (splitter: left | centre | right) ─────────────
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(2)
        splitter.setStyleSheet(
            f"QSplitter::handle {{ background: {T.BORDER}; }}"
        )
        root_layout.addWidget(splitter, 1)

        # ── Left column ────────────────────────────────────────────────
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(0)
        left_scroll.setStyleSheet(f"background: {T.BG_BASE};")
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(12, 12, 6, 12)
        left_layout.setSpacing(10)

        self.daq_widget         = DAQSetupWidget()
        self.test_config_widget = TestConfigWidget(self.log_directory)

        left_layout.addWidget(self.daq_widget)
        left_layout.addWidget(self.test_config_widget)
        left_layout.addStretch()
        left_scroll.setWidget(left_panel)
        splitter.addWidget(left_scroll)

        # ── Centre column ─────────────────────────────────────────────
        centre_panel = QWidget()
        centre_layout = QVBoxLayout(centre_panel)
        centre_layout.setContentsMargins(6, 12, 6, 12)
        centre_layout.setSpacing(10)

        self.uut_table_widget = UUTTableWidget()
        self.progress_widget  = ProgressWidget()
        self.log_widget       = LogWidget()

        centre_layout.addWidget(self.uut_table_widget, 3)
        centre_layout.addWidget(self.progress_widget)
        centre_layout.addWidget(self.log_widget, 2)
        splitter.addWidget(centre_panel)

        # ── Right column ──────────────────────────────────────────────
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(0)
        right_scroll.setStyleSheet(f"background: {T.BG_BASE};")
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(6, 12, 12, 12)
        right_layout.setSpacing(10)

        self.status_panel     = StatusPanelWidget()
        self.ibit_display     = IBITDisplayWidget()
        self.actuator_display = ActuatorFeedbackWidget()

        right_layout.addWidget(self.status_panel)
        right_layout.addWidget(self.ibit_display)
        right_layout.addWidget(self.actuator_display, 1)
        right_layout.addStretch()
        right_scroll.setWidget(right_panel)
        splitter.addWidget(right_scroll)

        # Proportional column widths
        splitter.setSizes([340, 820, 540])

        # ── Bottom bar ─────────────────────────────────────────────────
        bottom_bar = QWidget()
        bottom_bar.setStyleSheet(
            f"background-color: {T.BG_ELEVATED}; "
            f"border-top: 1px solid {T.BORDER};"
        )
        bottom_bar.setFixedHeight(80)
        bb_layout = QHBoxLayout(bottom_bar)
        bb_layout.setContentsMargins(16, 10, 16, 10)
        bb_layout.setSpacing(10)

        self.control_buttons = ControlButtonsWidget()
        bb_layout.addWidget(self.control_buttons)

        root_layout.addWidget(bottom_bar)

        # ── Status bar ────────────────────────────────────────────────
        self.statusBar = self.statusBar()
        self.statusBar.setFixedHeight(24)
        self.update_status_bar()

        # ── Signals ───────────────────────────────────────────────────
        self._connect_signals()

    def _connect_signals(self):
        self.daq_widget.detect_clicked.connect(self.detect_daq_devices)
        self.daq_widget.initialize_clicked.connect(self.initialize_daq)

        self.test_config_widget.log_dir_changed.connect(self.on_log_dir_changed)
        self.test_config_widget.browse_clicked.connect(self.browse_log_directory)
        self.test_config_widget.open_clicked.connect(self.open_log_directory)
        self.test_config_widget.mode_changed.connect(self.on_test_mode_changed)

        self.uut_table_widget.add_clicked.connect(self.add_uut)
        self.uut_table_widget.edit_clicked.connect(self.edit_uut)
        self.uut_table_widget.remove_clicked.connect(self.remove_uut)
        self.uut_table_widget.save_clicked.connect(self.save_uut_config)
        self.uut_table_widget.load_clicked.connect(self.load_uut_config)

        self.control_buttons.start_clicked.connect(self.start_all_tests)
        self.control_buttons.stop_clicked.connect(self.stop_test)
        self.control_buttons.emergency_clicked.connect(self.emergency_stop)

        self.elapsed_timer.timeout.connect(self.update_elapsed_time)

    # ═══════════════════════════════════════════════════════════════════════
    # DAQ management
    # ═══════════════════════════════════════════════════════════════════════

    def detect_daq_devices(self):
        devices = SimpleDAQController.detect_devices()
        self.daq_widget.set_devices(devices)
        if devices:
            self.log(f"✓ Found {len(devices)} DAQ device(s): {', '.join(devices)}")
            info = SimpleDAQController.get_device_info(devices[0])
            if info and 'do_lines' in info:
                self.log(f"  {devices[0]}: {len(info['do_lines'])} digital output lines")
        else:
            self.log("⚠ No NI-DAQmx devices found")
            QMessageBox.warning(self, "No Devices", "No NI-DAQmx devices found.")

    def initialize_daq(self):
        device = self.daq_widget.get_selected_device()
        if not device:
            QMessageBox.warning(self, "No Device", "Please select a DAQ device first.")
            return

        info = SimpleDAQController.get_device_info(device)
        if info and 'do_lines' in info:
            available = len(info['do_lines'])
            if self.uuts:
                max_relay = max(u.relay_line for u in self.uuts)
                if max_relay >= available:
                    QMessageBox.warning(
                        self, "Configuration Issue",
                        f"A UUT relay line ({max_relay}) exceeds the device range "
                        f"(0–{available-1}). Please reconfigure."
                    )
                    return

        success, message = self.daq.initialize(device, num_lines=8)
        if success:
            self.daq_widget.set_status(True, f"Ready  ({self.daq.num_lines} lines)")
            self.log(f"✓ DAQ initialized: {message}")
        else:
            self.daq_widget.set_status(False, "Error")
            self.log(f"✗ DAQ initialization failed: {message}")

    def check_daq_health(self):
        if not self.testing_active or not self.daq or not self.daq.do_task:
            return
        if not self.daq.verify_connection():
            self.log("⚠ DAQ connection lost — attempting reconnect...")
            success, msg = self.daq.reconnect()
            if success:
                self.log(f"✓ DAQ reconnected: {msg}")
            else:
                self.log(f"✗ DAQ reconnection failed: {msg}")
                self.alert_banner.show_alert(
                    f"DAQ OFFLINE — {msg}", severity='critical'
                )
                QMessageBox.critical(
                    self, "DAQ Connection Lost",
                    f"DAQ lost and could not reconnect.\n\n{msg}\n\n"
                    "Test will stop for safety."
                )
                self.stop_test()

    # ═══════════════════════════════════════════════════════════════════════
    # UUT management
    # ═══════════════════════════════════════════════════════════════════════

    def add_uut(self):
        dialog = AddUUTDialog(self)
        if dialog.exec_() == dialog.Accepted:
            uut = dialog.get_uut()
            # Check for duplicate relay line
            conflicts = [u for u in self.uuts if u.relay_line == uut.relay_line]
            if conflicts:
                QMessageBox.warning(
                    self, "Relay Conflict",
                    f"Relay line {uut.relay_line} is already assigned to "
                    f"UUT {conflicts[0].serial_number}.\n"
                    "Each UUT must have a unique relay line."
                )
                return
            self.uuts.append(uut)
            self.uut_table_widget.update_table(self.uuts)
            self.log(f"✓ Added UUT {uut.serial_number}  ({uut.ip_address}:{uut.port}  relay D{uut.relay_line})")

    def edit_uut(self):
        row = self.uut_table_widget.get_selected_row()
        if row == -1:
            QMessageBox.information(self, "No Selection", "Select a UUT to edit.")
            return
        uut = self.uuts[row]
        dialog = AddUUTDialog(self, uut)
        if dialog.exec_() == dialog.Accepted:
            updated = dialog.get_uut()
            self.uuts[row] = updated
            self.uut_table_widget.update_table(self.uuts)
            self.log(f"✓ Updated UUT {updated.serial_number}")

    def remove_uut(self):
        row = self.uut_table_widget.get_selected_row()
        if row == -1:
            QMessageBox.information(self, "No Selection", "Select a UUT to remove.")
            return
        uut = self.uuts[row]
        if QMessageBox.question(
            self, "Remove UUT",
            f"Remove UUT {uut.serial_number}?",
            QMessageBox.Yes | QMessageBox.No
        ) == QMessageBox.Yes:
            self.uuts.pop(row)
            self.uut_table_widget.update_table(self.uuts)
            self.log(f"Removed UUT {uut.serial_number}")

    def save_uut_config(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save UUT Configuration", "uut_config.json", "JSON (*.json)"
        )
        if path:
            with open(path, 'w') as f:
                json.dump({'uuts': [u.to_dict() for u in self.uuts]}, f, indent=2)
            self.log(f"✓ Saved {os.path.basename(path)}")

    def load_uut_config(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load UUT Configuration", "", "JSON (*.json)"
        )
        if path:
            with open(path) as f:
                cfg = json.load(f)
            self.uuts = [UUT.from_dict(d) for d in cfg['uuts']]
            self.uut_table_widget.update_table(self.uuts)
            self.log(f"✓ Loaded {len(self.uuts)} UUT(s) from {os.path.basename(path)}")

    # ═══════════════════════════════════════════════════════════════════════
    # Test control
    # ═══════════════════════════════════════════════════════════════════════

    def start_all_tests(self):
        # Prerequisites
        if not self.daq.do_task:
            QMessageBox.warning(self, "DAQ Not Ready",
                "Initialize the DAQ device before starting.")
            return
        if not self.uuts:
            QMessageBox.warning(self, "No UUTs",
                "Add at least one UUT before starting.")
            return

        duration_value, unit = self.test_config_widget.get_duration()
        multiplier = {"Seconds": 1, "Minutes": 60, "Hours": 3600, "Days": 86400}[unit]
        duration_seconds = duration_value * multiplier

        test_mode    = self.test_config_widget.get_test_mode()
        playback_csv = self.test_config_widget.get_playback_csv()
        playback_type = self.test_config_widget.get_playback_type()

        if test_mode == 'playback' and not playback_csv:
            QMessageBox.warning(self, "No Profile",
                "Select a flight profile CSV before starting Playback mode.")
            return
        if test_mode == 'playback' and not os.path.isfile(playback_csv):
            QMessageBox.warning(self, "Profile Not Found",
                f"The CSV file no longer exists:\n{playback_csv}\n\n"
                "Please re-select the file.")
            return

        mode_label = (
            "IBIT Test" if test_mode == 'ibit'
            else f"Flight Profile Playback  ({playback_type})"
        )

        # Check for relay conflicts
        relay_lines = [u.relay_line for u in self.uuts]
        if len(relay_lines) != len(set(relay_lines)):
            QMessageBox.warning(self, "Relay Conflict",
                "Two or more UUTs share the same relay line.\n"
                "Each UUT must have a unique relay line.")
            return

        if QMessageBox.question(
            self, "Confirm Start",
            f"Start  {mode_label}\n"
            f"Duration:  {duration_value} {unit}\n"
            f"UUTs:  {len(self.uuts)}\n\n"
            f"Logs → {self.log_directory}",
            QMessageBox.Yes | QMessageBox.No
        ) != QMessageBox.Yes:
            return

        # Reset
        for uut in self.uuts:
            uut.status = "Ready"
            uut.iterations_completed = 0
        self.uut_table_widget.update_table(self.uuts)

        self.testing_active       = True
        self.batch_start_datetime = datetime.now()
        self.batch_end_time       = self.batch_start_datetime.timestamp() + duration_seconds
        self.current_uut_index    = -1
        self.test_mode            = test_mode
        self.playback_csv         = playback_csv
        self.playback_type        = playback_type

        self.test_config.update(self.test_config_widget.get_config())
        self.control_buttons.set_testing_mode(True)
        self.alert_banner.hide()

        self.log("═" * 56)
        self.log(f"  BATCH START  —  {mode_label}")
        self.log(f"  {self.batch_start_datetime.strftime('%Y-%m-%d %H:%M:%S')}  "
                 f"Duration: {duration_value} {unit}")
        self.log("═" * 56)

        self.elapsed_timer.start(1000)
        self.start_next_uut()

        if platform.system() == "Windows":
            try:
                import ctypes
                ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)
                self.log("✓ Windows sleep prevention active")
            except Exception:
                pass

    def start_next_uut(self):
        if time.time() >= self.batch_end_time:
            self.batch_complete()
            return

        self.current_uut_index = (self.current_uut_index + 1) % len(self.uuts)
        uut = self.uuts[self.current_uut_index]

        if not hasattr(uut, 'consecutive_failures'):
            uut.consecutive_failures = 0

        if uut.status == "Failed (3x)":
            self.log(f"  Skipping {uut.serial_number} (permanently failed)")
            QTimer.singleShot(100, self.start_next_uut)
            return

        uut.status = "Testing"
        self.uut_table_widget.update_table(self.uuts)
        self.progress_widget.set_current_uut(
            f"UUT {self.current_uut_index+1}/{len(self.uuts)}  —  {uut.serial_number}"
        )

        skip = self.test_config_widget.get_skip_state_management()

        if self.test_mode == 'playback':
            self.current_test_executor = PlaybackTestExecutor(
                uut, self.daq, self.batch_end_time,
                self.test_config_widget.get_stabilization_delay(),
                self.test_config_widget.get_connection_timeout(),
                self.log_directory, self.batch_start_datetime,
                playback_csv=self.playback_csv,
                playback_type=self.playback_type,
                config=self.test_config,
            )
        else:
            self.current_test_executor = UUTTestExecutor(
                uut, self.daq, self.batch_end_time,
                self.test_config_widget.get_stabilization_delay(),
                self.test_config_widget.get_connection_timeout(),
                self.log_directory, self.batch_start_datetime,
                skip_state_management=skip,
                config=self.test_config,
            )

        # Common signals
        ex = self.current_test_executor
        ex.test_complete.connect(self.on_uut_test_complete)
        ex.time_expired.connect(self.on_batch_time_expired)
        ex.log_message.connect(self.log)
        ex.connection_health_update.connect(self.status_panel.set_connection_health)
        ex.alert_update.connect(self.show_alert)
        ex.test_duration_update.connect(self.ibit_display.set_duration)
        ex.armed_state_update.connect(self.status_panel.set_armed_state)
        ex.mode_update.connect(self.status_panel.set_mode)
        ex.actuator_feedback_update.connect(self.actuator_display.update_feedback)
        ex.status_update.connect(self._on_prep_status)

        if self.test_mode == 'ibit':
            ex.iteration_update.connect(self.progress_widget.set_iteration)
            ex.statistics_update.connect(self._on_statistics)
            ex.ibit_state_update.connect(self.ibit_display.set_substate)
        else:
            ex.progress_update.connect(self.ibit_display.set_playback_progress)

        ex.start()

    def on_uut_test_complete(self, success, message):
        uut = self.uuts[self.current_uut_index]

        if not success and "Batch time expired" not in message:
            uut.consecutive_failures = getattr(uut, 'consecutive_failures', 0) + 1
            if uut.consecutive_failures >= 3:
                uut.status = "Failed (3x)"
                self.log(f"⚠ {uut.serial_number} failed 3× — permanently skipping")
                if self.daq:
                    ok, msg = self.daq.set_line(uut.relay_line, False)
                    self.log(f"  Relay D{uut.relay_line} {'disabled' if ok else 'ERROR: ' + msg}")
            else:
                uut.status = "Retry"
                self.log(
                    f"⚠ {uut.serial_number} failed "
                    f"({uut.consecutive_failures}/3) — will retry"
                )
        else:
            uut.consecutive_failures = 0
            if success:
                uut.status = "Complete"

        self.log(f"{'✓' if success else '✗'}  {uut.serial_number}: {message}")
        self.uut_table_widget.update_table(self.uuts)

        if success:
            self.alert_banner.hide()

        if self.testing_active and time.time() < self.batch_end_time:
            QTimer.singleShot(2000, self.start_next_uut)
        elif self.testing_active:
            self.batch_complete()

    def on_batch_time_expired(self):
        self.batch_complete()

    def batch_complete(self):
        self.testing_active = False
        self.elapsed_timer.stop()

        if 0 <= self.current_uut_index < len(self.uuts):
            uut = self.uuts[self.current_uut_index]
            if self.daq:
                ok, msg = self.daq.set_line(uut.relay_line, False)
                self.log(f"  Final relay D{uut.relay_line} {'disabled' if ok else 'ERROR: '+msg}")

        for uut in self.uuts:
            if uut.status in ("Testing", "Ready"):
                uut.status = "Complete"
        self.uut_table_widget.update_table(self.uuts)

        self.log("═" * 56)
        self.log(f"  BATCH COMPLETE  —  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self.log("═" * 56)

        self.generate_batch_report()
        self.control_buttons.set_testing_mode(False)
        self.progress_widget.set_current_uut("Complete")
        self.status_panel.reset()
        self.ibit_display.reset()
        self.actuator_display.reset()

        total = sum(u.iterations_completed for u in self.uuts)
        QMessageBox.information(
            self, "Batch Complete",
            f"Batch test finished.\n\n"
            f"Total iterations: {total:,}\n"
            f"Logs: {self.log_directory}"
        )

        if platform.system() == "Windows":
            try:
                import ctypes
                ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
            except Exception:
                pass

    def stop_test(self):
        if QMessageBox.question(
            self, "Stop Test",
            "Stop the current batch?\n\nThe active test will complete its cleanup safely.",
            QMessageBox.Yes | QMessageBox.No
        ) != QMessageBox.Yes:
            return

        self.log("⚠ Stop requested — graceful shutdown...")
        self.testing_active = False
        self.elapsed_timer.stop()

        if self.current_test_executor:
            self.current_test_executor.stop()
            self.control_buttons.set_enabled(False, False)
            self.progress_widget.set_current_uut("Stopping...")
            QApplication.processEvents()

            wait_start = time.time()
            while self.current_test_executor.isRunning() and time.time()-wait_start < 15:
                QApplication.processEvents()
                time.sleep(0.1)

            if not self.current_test_executor.isRunning():
                self.log("✓ Test thread stopped cleanly")
            else:
                self.log("⚠ Forcing termination")
                self.current_test_executor.terminate()
                self.current_test_executor.wait(2000)
            self.current_test_executor = None

        if 0 <= self.current_uut_index < len(self.uuts):
            uut = self.uuts[self.current_uut_index]
            if self.daq:
                ok, msg = self.daq.set_line(uut.relay_line, False)
                self.log(f"  Relay D{uut.relay_line} {'disabled' if ok else 'ERROR: '+msg}")
            uut.status = "Stopped"
            self.uut_table_widget.update_table(self.uuts)

        self.control_buttons.set_testing_mode(False)
        self.progress_widget.set_current_uut("Stopped")
        self.status_panel.reset()
        self.ibit_display.reset()
        self.actuator_display.reset()
        self.alert_banner.hide()
        self.log("✓ Stop complete")

    def emergency_stop(self):
        self.log("⚠⚠⚠ EMERGENCY STOP")
        self.testing_active = False
        if self.current_test_executor:
            self.current_test_executor.stop()
        if self.daq.do_task:
            self.daq.set_all_low()
            self.log("  All relays disabled")
        self.elapsed_timer.stop()
        self.control_buttons.set_testing_mode(False)
        self.alert_banner.show_alert(
            "EMERGENCY STOP — All relays disabled", severity='critical'
        )
        QMessageBox.critical(
            self, "Emergency Stop",
            "EMERGENCY STOP activated.\nAll relay outputs set to LOW.\n"
            "Verify vehicle hardware before resuming."
        )

    # ═══════════════════════════════════════════════════════════════════════
    # Utility
    # ═══════════════════════════════════════════════════════════════════════

    def on_test_mode_changed(self, mode):
        self.test_mode = mode
        self.ibit_display.set_mode(mode)
        self.control_buttons.set_test_mode_label(mode)
        self.progress_widget.set_test_mode(mode)
        self.header.set_mode(mode)
        mode_str = "IBIT" if mode == 'ibit' else "Flight Profile Playback"
        self.setWindowTitle(f"Roadrunner Flight Test  —  {mode_str}")
        self.update_status_bar()

    def update_elapsed_time(self):
        if self.batch_start_datetime and self.testing_active:
            elapsed   = time.time() - self.batch_start_datetime.timestamp()
            remaining = max(0, self.batch_end_time - time.time())
            self.progress_widget.set_elapsed(elapsed)
            self.progress_widget.set_remaining(remaining)
            total = self.batch_end_time - self.batch_start_datetime.timestamp()
            self.progress_widget.set_progress(min(100, int(elapsed/total*100)))

    def _on_statistics(self, statistics):
        self.current_statistics = statistics

    def _on_prep_status(self, status_text):
        """Show preparation phase progress in the Test Status widget."""
        # Map common preparation messages to short labels
        text = status_text.strip()
        if 'Connecting' in text:
            self.ibit_display.set_substate('CONNECTING')
        elif 'ARM' in text or 'Arming' in text:
            self.ibit_display.set_substate('ARMING')
        elif 'PLAYBACK' in text:
            self.ibit_display.set_substate('PLAYBACK')
        elif 'IBIT' in text:
            self.ibit_display.set_substate('ENTERING IBIT')
        elif 'monitor' in text.lower():
            self.ibit_display.set_substate('CLEARING MONITORS')
        elif 'Capturing' in text or 'capture' in text.lower():
            self.ibit_display.set_substate('CAPTURING STATE')

    def show_alert(self, message):
        severity = 'critical' if 'CRITICAL' in message.upper() else 'warning'
        self.alert_banner.show_alert(message, severity=severity)

    def generate_batch_report(self):
        tag  = 'IBIT' if self.test_mode == 'ibit' else 'Playback'
        path = os.path.join(
            self.report_directory,
            f"BatchTest_{tag}_v5.0_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        report = {
            'test_type':   f'{tag}_v5.0',
            'version':     '5.0',
            'test_mode':   self.test_mode,
            'start':       self.batch_start_datetime.strftime('%Y-%m-%d %H:%M:%S'),
            'end':         datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'duration_s':  time.time() - self.batch_start_datetime.timestamp(),
            'log_dir':     self.log_directory,
            'test_config': self.test_config,
            'uuts': [{
                'serial':     u.serial_number,
                'ip':         u.ip_address,
                'status':     u.status,
                'iterations': u.iterations_completed,
                'log_file':   u.log_file,
            } for u in self.uuts],
        }
        try:
            with open(path, 'w') as f:
                json.dump(report, f, indent=2)
            self.log(f"✓ Report saved: {path}")
            self.alert_banner.show_alert(
                f"Batch report saved: {os.path.basename(path)}",
                severity='info', auto_hide_ms=15000
            )
        except Exception as e:
            self.log(f"✗ Report save failed: {e}")

    def browse_log_directory(self):
        d = QFileDialog.getExistingDirectory(self, "Select Log Directory", self.log_directory)
        if d:
            self.log_directory = d
            self.test_config_widget.set_log_directory(d)
            self.update_status_bar()
            self.log(f"Log directory → {d}")

    def open_log_directory(self):
        try:
            if platform.system() == "Windows":
                os.startfile(self.log_directory)
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", self.log_directory])
            else:
                subprocess.Popen(["xdg-open", self.log_directory])
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not open directory: {e}")

    def on_log_dir_changed(self, directory):
        self.log_directory = directory
        self.update_status_bar()

    def update_status_bar(self):
        mode_str = "IBIT" if self.test_mode == 'ibit' else "Playback"
        self.statusBar.showMessage(
            f"Mode: {mode_str}   |   Logs: {self.log_directory}   |   v5.0"
        )

    def log(self, message):
        self.log_widget.append(message)

    def save_settings(self):
        cfg = {
            'log_directory':    self.log_directory,
            'report_directory': self.report_directory,
            'test_config':      self.test_config,
        }
        cfg.update(self.test_config_widget.get_all_settings())
        path = os.path.join(self.project_root, "app_settings.json")
        try:
            with open(path, 'w') as f:
                json.dump(cfg, f, indent=2)
        except Exception as e:
            self.log(f"⚠ Could not save settings: {e}")

    def load_settings(self):
        """Load application settings"""
        path = os.path.join(self.project_root, "app_settings.json")
        if not os.path.exists(path):
            return
        try:
            with open(path) as f:
                cfg = json.load(f)
            self.log_directory    = cfg.get('log_directory',    self.log_directory)
            self.report_directory = cfg.get('report_directory', self.report_directory)
            self.test_config_widget.load_settings(cfg)
            self.update_status_bar()
            self.log("✓ Settings loaded")
        except Exception as e:
            self.log(f"⚠ Could not load settings: {e}")

    # ═══════════════════════════════════════════════════════════════════════
    # Remote command server
    # ═══════════════════════════════════════════════════════════════════════

    def _start_command_server(self):
        """Start a TCP command server on localhost for remote control."""
        def _server():
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                srv.bind(('127.0.0.1', self.COMMAND_PORT))
                srv.listen(1)
                srv.settimeout(1.0)
                self.log(f"Command server listening on port {self.COMMAND_PORT}")
            except OSError as e:
                self.log(f"Command server failed to start: {e}")
                return

            while True:
                try:
                    conn, addr = srv.accept()
                    data = conn.recv(4096).decode('utf-8')
                    if data:
                        try:
                            req = json.loads(data)
                            cmd = req.get('cmd', '')
                            args = req.get('args', {})

                            # Execute on GUI thread via signal
                            self._cmd_event.clear()
                            self._cmd_response = {}
                            self._remote_cmd.emit(cmd, args)

                            # Wait for GUI thread to process (up to 30s)
                            self._cmd_event.wait(timeout=30.0)
                            response = self._cmd_response
                        except json.JSONDecodeError:
                            response = {'error': 'Invalid JSON'}

                        conn.sendall(json.dumps(response).encode('utf-8'))
                    conn.close()
                except socket.timeout:
                    continue
                except Exception:
                    break

        t = threading.Thread(target=_server, daemon=True)
        t.start()

    def _execute_remote_command(self, cmd, args):
        """Execute a remote command on the GUI thread."""
        try:
            if cmd == 'start':
                # Bypass QMessageBox confirmation
                self._auto_start_test(int(args.get('seconds', 120)))
                self._cmd_response = {'ok': True, 'msg': 'Test started'}

            elif cmd == 'stop':
                self.testing_active = False
                if self.current_test_executor:
                    self.current_test_executor.stop()
                self._cmd_response = {'ok': True, 'msg': 'Stop requested'}

            elif cmd == 'emergency':
                self.emergency_stop()
                self._cmd_response = {'ok': True, 'msg': 'Emergency stop'}

            elif cmd == 'status':
                uut_statuses = [
                    {'serial': u.serial_number, 'status': u.status,
                     'iterations': u.iterations_completed}
                    for u in self.uuts
                ]
                self._cmd_response = {
                    'ok': True,
                    'testing': self.testing_active,
                    'mode': self.test_mode,
                    'uuts': uut_statuses,
                    'elapsed': time.time() - self.batch_start_datetime.timestamp()
                    if self.batch_start_datetime and self.testing_active else 0,
                }

            elif cmd == 'screenshot':
                path = os.path.join(
                    self.project_root, 'screenshots',
                    f'remote_{datetime.now().strftime("%Y%m%d_%H%M%S")}.png'
                )
                os.makedirs(os.path.dirname(path), exist_ok=True)
                pixmap = self.grab()
                pixmap.save(path, 'PNG')
                self._cmd_response = {'ok': True, 'path': path,
                                      'size': f'{pixmap.width()}x{pixmap.height()}'}

            elif cmd == 'set_duration':
                secs = int(args.get('seconds', 120))
                if secs < 60:
                    self.test_config_widget.duration_input.setValue(secs)
                    self.test_config_widget.duration_unit_combo.setCurrentText("Seconds")
                elif secs < 3600:
                    self.test_config_widget.duration_input.setValue(secs // 60)
                    self.test_config_widget.duration_unit_combo.setCurrentText("Minutes")
                else:
                    self.test_config_widget.duration_input.setValue(secs // 3600)
                    self.test_config_widget.duration_unit_combo.setCurrentText("Hours")
                self._cmd_response = {'ok': True, 'seconds': secs}

            else:
                self._cmd_response = {'error': f'Unknown command: {cmd}'}

        except Exception as e:
            self._cmd_response = {'error': str(e)}
        finally:
            self._cmd_event.set()

    def _auto_start_test(self, duration_seconds=120):
        """Start the test programmatically without QMessageBox confirmation."""
        if not self.daq.do_task:
            raise Exception("DAQ not initialized")
        if not self.uuts:
            raise Exception("No UUTs configured")

        # Set duration
        self.test_config_widget.duration_input.setValue(duration_seconds)
        self.test_config_widget.duration_unit_combo.setCurrentText("Seconds")

        test_mode = self.test_config_widget.get_test_mode()
        playback_csv = self.test_config_widget.get_playback_csv()
        playback_type = self.test_config_widget.get_playback_type()

        # Reset UUTs
        for uut in self.uuts:
            uut.status = "Ready"
            uut.iterations_completed = 0
        self.uut_table_widget.update_table(self.uuts)

        self.testing_active = True
        self.batch_start_datetime = datetime.now()
        self.batch_end_time = self.batch_start_datetime.timestamp() + duration_seconds
        self.current_uut_index = -1
        self.test_mode = test_mode
        self.playback_csv = playback_csv
        self.playback_type = playback_type

        self.test_config.update(self.test_config_widget.get_config())
        self.control_buttons.set_testing_mode(True)

        mode_label = "IBIT" if test_mode == 'ibit' else f"Playback ({playback_type})"
        self.log("=" * 56)
        self.log(f"  BATCH START  --  {mode_label}  ({duration_seconds}s)")
        self.log("=" * 56)

        self.elapsed_timer.start(1000)
        self.start_next_uut()

    def closeEvent(self, event):
        if self.testing_active:
            reply = QMessageBox.question(
                self, "Test Running",
                "A test is running. Stop and exit?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                event.ignore()
                return
        self.save_settings()
        if self.daq:
            self.daq.close()
        event.accept()
