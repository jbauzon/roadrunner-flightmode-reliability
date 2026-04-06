"""
Main Window - Primary GUI for multi-UUT testing

This module contains the main application window and orchestrates
batch testing across multiple UUTs.
"""
import os
import json
import time
import shutil
import platform
import subprocess
from datetime import datetime
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QMessageBox, QFileDialog, QApplication
)
from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QFont

from hardware.daq import SimpleDAQController
from vehicle.connection import UUT
from test.executor import UUTTestExecutor, PlaybackTestExecutor
from .widgets import (
    DAQSetupWidget, TestConfigWidget, UUTTableWidget,
    StatusPanelWidget, IBITDisplayWidget, ActuatorFeedbackWidget,
    AlertBannerWidget, ProgressWidget, ControlButtonsWidget,
    LogWidget, AddUUTDialog
)


class MultiUUTTestGUI(QMainWindow):
    """
    Main window with complete IBIT mode sequence handling.
    
    Manages:
    - DAQ initialization
    - UUT configuration
    - Batch test orchestration
    - Multi-UUT sequential testing
    - Progress tracking
    - Real-time status display
    """
    
    def __init__(self):
        """Initialize main window"""
        super().__init__()
        
        # Directories
        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        self.log_directory = os.path.join(self.script_dir, "..", "logs")
        self.report_directory = os.path.join(self.script_dir, "..", "reports")
        os.makedirs(self.log_directory, exist_ok=True)
        os.makedirs(self.report_directory, exist_ok=True)
        
        # Hardware
        self.daq = SimpleDAQController()
        
        # UUTs and testing state
        self.uuts = []
        self.current_test_executor = None
        self.current_uut_index = -1
        self.batch_start_datetime = None
        self.batch_end_time = None
        self.testing_active = False
        self.current_statistics = None
        self.test_mode = 'ibit'
        self.playback_csv = ''
        self.playback_type = 'Actuation'
        
        # Test configuration
        self.test_config = {
            'ibit_timeout': 300.0,
            'phase_timeout': 90.0,
            'arm_timeout': 60.0,
            'max_arm_iterations': 20,
            'skip_arm_for_ibit': False
        }
        
        # Initialize timers BEFORE init_ui (which calls _connect_signals)
        self.daq_health_timer = QTimer()
        self.elapsed_timer = QTimer()
        
        # Build UI
        self.init_ui()
        
        # Configure timers AFTER UI is built
        self.daq_health_timer.timeout.connect(self.check_daq_health)
        self.daq_health_timer.start(60000)  # Check every minute
        
        # Load settings after UI is built
        QTimer.singleShot(100, self.load_settings)
        QTimer.singleShot(500, self.detect_daq_devices)
        # Apply initial mode to UI (in case saved settings loaded playback mode)
        QTimer.singleShot(200, lambda: self.on_test_mode_changed(
            self.test_config_widget.get_test_mode()
        ))
    
    def init_ui(self):
        """Initialize user interface"""
        self.setWindowTitle(
            "Multi-UUT Flight Controller Test System v5.0 — IBIT"
        )
        self.setGeometry(50, 50, 1800, 1000)
        
        # Central widget with scroll area
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout()
        main_widget.setLayout(main_layout)
        
        # Create widgets
        self.daq_widget = DAQSetupWidget()
        self.test_config_widget = TestConfigWidget(self.log_directory)
        self.uut_table_widget = UUTTableWidget()
        self.status_panel = StatusPanelWidget()
        self.ibit_display = IBITDisplayWidget()
        self.actuator_display = ActuatorFeedbackWidget()
        self.alert_banner = AlertBannerWidget()
        self.progress_widget = ProgressWidget()
        self.control_buttons = ControlButtonsWidget()
        self.log_widget = LogWidget()
        
        # Layout
        top_layout = QHBoxLayout()
        
        # Left column
        left_column = QVBoxLayout()
        left_column.addWidget(self.daq_widget)
        left_column.addWidget(self.test_config_widget)
        left_column.addWidget(self.uut_table_widget)
        top_layout.addLayout(left_column, 50)
        
        # Right column
        right_column = QVBoxLayout()
        right_column.addWidget(self.status_panel)
        right_column.addWidget(self.ibit_display)
        right_column.addWidget(self.actuator_display)
        top_layout.addLayout(right_column, 50)
        
        # Add to main layout
        main_layout.addLayout(top_layout)
        main_layout.addWidget(self.alert_banner)
        main_layout.addWidget(self.progress_widget)
        main_layout.addWidget(self.control_buttons)
        main_layout.addWidget(self.log_widget)
        
        # Connect signals
        self._connect_signals()
        
        # Status bar
        self.statusBar = self.statusBar()
        self.update_status_bar()
    
    def _connect_signals(self):
        """Connect widget signals to handlers"""
        # DAQ
        self.daq_widget.detect_clicked.connect(self.detect_daq_devices)
        self.daq_widget.initialize_clicked.connect(self.initialize_daq)
        
        # Test config
        self.test_config_widget.log_dir_changed.connect(self.on_log_dir_changed)
        self.test_config_widget.browse_clicked.connect(self.browse_log_directory)
        self.test_config_widget.open_clicked.connect(self.open_log_directory)
        self.test_config_widget.mode_changed.connect(self.on_test_mode_changed)
        
        # UUT table
        self.uut_table_widget.add_clicked.connect(self.add_uut)
        self.uut_table_widget.edit_clicked.connect(self.edit_uut)
        self.uut_table_widget.remove_clicked.connect(self.remove_uut)
        self.uut_table_widget.save_clicked.connect(self.save_uut_config)
        self.uut_table_widget.load_clicked.connect(self.load_uut_config)
        
        # Control buttons
        self.control_buttons.start_clicked.connect(self.start_all_tests)
        self.control_buttons.stop_clicked.connect(self.stop_test)
        self.control_buttons.emergency_clicked.connect(self.emergency_stop)
        
        # Progress timer
        self.elapsed_timer.timeout.connect(self.update_elapsed_time)
    
    # ========== DAQ MANAGEMENT ==========
    
    def detect_daq_devices(self):
        """Detect available DAQ devices"""
        devices = SimpleDAQController.detect_devices()
        self.daq_widget.set_devices(devices)
        
        if devices:
            self.log(f"Found {len(devices)} DAQ device(s): {', '.join(devices)}")
            if devices:
                info = SimpleDAQController.get_device_info(devices[0])
                if info and 'do_lines' in info:
                    self.log(
                        f"  {devices[0]}: {len(info['do_lines'])} "
                        f"digital output lines available"
                    )
        else:
            self.log("No DAQ devices found")
            QMessageBox.warning(
                self,
                "No Devices",
                "No NI-DAQmx devices found."
            )
    
    def initialize_daq(self):
        """Initialize selected DAQ device"""
        device = self.daq_widget.get_selected_device()
        if not device:
            QMessageBox.warning(self, "No Device", "Please select a DAQ device")
            return
        
        # Check if any UUT relay lines exceed available lines
        info = SimpleDAQController.get_device_info(device)
        if info and 'do_lines' in info:
            available_lines = len(info['do_lines'])
            self.log(f"Device {device} has {available_lines} digital output lines")
            
            max_relay_line = max([uut.relay_line for uut in self.uuts]) if self.uuts else 0
            if max_relay_line >= available_lines:
                QMessageBox.warning(
                    self,
                    "Configuration Issue",
                    f"Some UUTs are configured for relay lines that don't exist.\n"
                    f"Device has {available_lines} lines (0-{available_lines-1})\n"
                    f"Max configured relay line: {max_relay_line}"
                )
                return
        
        success, message = self.daq.initialize(device, num_lines=8)
        
        if success:
            self.daq_widget.set_status(
                True,
                f"Initialized ({self.daq.num_lines} lines)"
            )
            self.log(f"✓ DAQ initialized: {message}")
        else:
            self.daq_widget.set_status(False, "Error")
            self.log(f"✗ DAQ initialization failed: {message}")
    
    def check_daq_health(self):
        """Periodically verify DAQ is still connected"""
        if not self.testing_active or not self.daq or not self.daq.do_task:
            return
        
        if not self.daq.verify_connection():
            self.log("⚠⚠⚠ DAQ CONNECTION LOST ⚠⚠⚠")
            self.log("→ Attempting automatic reconnection...")
            
            success, msg = self.daq.reconnect()
            if success:
                self.log(f"✓ DAQ reconnected successfully: {msg}")
            else:
                self.log(f"✗ DAQ reconnection FAILED: {msg}")
                self.alert_banner.show_alert(f"CRITICAL: DAQ OFFLINE - {msg}")
                
                QMessageBox.critical(
                    self,
                    "DAQ Connection Lost",
                    f"DAQ connection lost and reconnection failed.\n\n"
                    f"Error: {msg}\n\n"
                    f"Test will be stopped for safety.",
                    QMessageBox.Ok
                )
                
                self.stop_test()
    
    # ========== UUT MANAGEMENT ==========
    
    def add_uut(self):
        """Add new UUT"""
        dialog = AddUUTDialog(self)
        if dialog.exec_() == dialog.Accepted:
            uut = dialog.get_uut()
            self.uuts.append(uut)
            self.uut_table_widget.update_table(self.uuts)
            self.log(f"Added UUT: {uut.serial_number} ({uut.ip_address}:{uut.port})")
    
    def edit_uut(self):
        """Edit selected UUT"""
        selected_row = self.uut_table_widget.get_selected_row()
        if selected_row == -1:
            QMessageBox.warning(self, "No Selection", "Please select a UUT to edit")
            return
        
        uut = self.uuts[selected_row]
        dialog = AddUUTDialog(self, uut)
        if dialog.exec_() == dialog.Accepted:
            updated_uut = dialog.get_uut()
            self.uuts[selected_row] = updated_uut
            self.uut_table_widget.update_table(self.uuts)
            self.log(f"Updated UUT: {updated_uut.serial_number}")
    
    def remove_uut(self):
        """Remove selected UUT"""
        selected_row = self.uut_table_widget.get_selected_row()
        if selected_row == -1:
            QMessageBox.warning(self, "No Selection", "Please select a UUT to remove")
            return
        
        uut = self.uuts[selected_row]
        if QMessageBox.question(
            self,
            "Confirm Remove",
            f"Remove UUT {uut.serial_number}?",
            QMessageBox.Yes | QMessageBox.No
        ) == QMessageBox.Yes:
            self.uuts.pop(selected_row)
            self.uut_table_widget.update_table(self.uuts)
            self.log(f"Removed UUT: {uut.serial_number}")
    
    def save_uut_config(self):
        """Save UUT configuration to file"""
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save UUT Configuration",
            "uut_config.json",
            "JSON Files (*.json)"
        )
        
        if file_path:
            with open(file_path, 'w') as f:
                json.dump({'uuts': [u.to_dict() for u in self.uuts]}, f, indent=2)
            self.log(f"✓ Saved configuration to {os.path.basename(file_path)}")
    
    def load_uut_config(self):
        """Load UUT configuration from file"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Load UUT Configuration",
            "",
            "JSON Files (*.json)"
        )
        
        if file_path:
            with open(file_path, 'r') as f:
                config = json.load(f)
            self.uuts = [UUT.from_dict(d) for d in config['uuts']]
            self.uut_table_widget.update_table(self.uuts)
            self.log(f"✓ Loaded {len(self.uuts)} UUT(s) from {os.path.basename(file_path)}")
    
    # ========== TEST CONTROL ==========
    
    def start_all_tests(self):
        """Start batch testing"""
        # Validate prerequisites
        if not self.daq.do_task:
            QMessageBox.warning(self, "DAQ Not Ready", "Please initialize DAQ first")
            return
        
        if not self.uuts:
            QMessageBox.warning(self, "No UUTs", "Please add at least one UUT")
            return
        
        # Get test duration
        duration_value, unit = self.test_config_widget.get_duration()
        multiplier = {"Seconds": 1, "Minutes": 60, "Hours": 3600, "Days": 86400}[unit]
        duration_seconds = duration_value * multiplier

        # Get test mode
        test_mode = self.test_config_widget.get_test_mode()
        playback_csv = self.test_config_widget.get_playback_csv()
        playback_type = self.test_config_widget.get_playback_type()

        if test_mode == 'playback' and not playback_csv:
            QMessageBox.warning(
                self,
                "No Profile Selected",
                "Please select a flight profile CSV before starting playback mode."
            )
            return

        if test_mode == 'playback' and not os.path.isfile(playback_csv):
            QMessageBox.warning(
                self,
                "Profile Not Found",
                f"The selected CSV file no longer exists:\n{playback_csv}\n\n"
                "Please select a valid flight profile CSV."
            )
            return

        # Confirm start
        mode_label = (
            "IBIT Test"
            if test_mode == 'ibit'
            else f"Flight Profile Playback ({playback_type})"
        )
        if QMessageBox.question(
            self,
            "Confirm Start",
            f"Start {mode_label} for {duration_value} {unit}?\n\n"
            f"Logs saved to:\n{self.log_directory}",
            QMessageBox.Yes | QMessageBox.No
        ) != QMessageBox.Yes:
            return
        
        # Reset UUTs
        for uut in self.uuts:
            uut.status = "Ready"
            uut.iterations_completed = 0
        self.uut_table_widget.update_table(self.uuts)
        
        # Initialize batch
        self.testing_active = True
        self.batch_start_datetime = datetime.now()
        self.batch_end_time = self.batch_start_datetime.timestamp() + duration_seconds
        self.current_uut_index = -1
        self.test_mode = test_mode
        self.playback_csv = playback_csv
        self.playback_type = playback_type
        
        # Update test config
        self.test_config.update(self.test_config_widget.get_config())
        
        # Update UI
        self.control_buttons.set_testing_mode(True)
        
        self.log("═══════════════════════════════════════")
        self.log(f"STARTING TEST BATCH — Mode: {mode_label}")
        self.log(f"Start Time: {self.batch_start_datetime.strftime('%Y-%m-%d %H:%M:%S')}")
        self.log(f"Duration: {duration_value} {unit}")
        self.log(f"Log Directory: {self.log_directory}")
        self.log("═══════════════════════════════════════")
        
        self.elapsed_timer.start(1000)
        self.start_next_uut()
        
        # Prevent system sleep on Windows
        if platform.system() == "Windows":
            try:
                import ctypes
                ES_CONTINUOUS = 0x80000000
                ES_SYSTEM_REQUIRED = 0x00000001
                ctypes.windll.kernel32.SetThreadExecutionState(
                    ES_CONTINUOUS | ES_SYSTEM_REQUIRED
                )
                self.log("✓ Windows sleep prevention enabled")
            except Exception as e:
                self.log(f"⚠ Could not prevent Windows sleep: {e}")
    
    def start_next_uut(self):
        """Start testing next UUT in sequence"""
        if time.time() >= self.batch_end_time:
            self.batch_complete()
            return
        
        self.current_uut_index = (self.current_uut_index + 1) % len(self.uuts)
        uut = self.uuts[self.current_uut_index]
        
        # Add retry counter
        if not hasattr(uut, 'consecutive_failures'):
            uut.consecutive_failures = 0
        
        # Skip permanently failed UUTs
        if uut.status == "Failed (3x)":
            self.log(f"⚠ Skipping UUT {uut.serial_number} (permanently failed)")
            QTimer.singleShot(100, self.start_next_uut)
            return
        
        uut.status = "Testing"
        self.uut_table_widget.update_table(self.uuts)
        
        self.progress_widget.set_current_uut(
            f"UUT {self.current_uut_index + 1}/{len(self.uuts)} - {uut.serial_number}"
        )
        
        # Create test executor
        skip_state_mgmt = self.test_config_widget.get_skip_state_management()

        if self.test_mode == 'playback':
            self.current_test_executor = PlaybackTestExecutor(
                uut,
                self.daq,
                self.batch_end_time,
                self.test_config_widget.get_stabilization_delay(),
                self.test_config_widget.get_connection_timeout(),
                self.log_directory,
                self.batch_start_datetime,
                playback_csv=self.playback_csv,
                playback_type=self.playback_type,
                config=self.test_config
            )
        else:
            self.current_test_executor = UUTTestExecutor(
                uut,
                self.daq,
                self.batch_end_time,
                self.test_config_widget.get_stabilization_delay(),
                self.test_config_widget.get_connection_timeout(),
                self.log_directory,
                self.batch_start_datetime,
                skip_state_management=skip_state_mgmt,
                config=self.test_config
            )
        
        # Connect common signals
        self.current_test_executor.test_complete.connect(self.on_uut_test_complete)
        self.current_test_executor.time_expired.connect(self.on_batch_time_expired)
        self.current_test_executor.log_message.connect(self.log)
        self.current_test_executor.connection_health_update.connect(
            self.status_panel.set_connection_health
        )
        self.current_test_executor.alert_update.connect(self.show_alert)
        self.current_test_executor.test_duration_update.connect(
            self.ibit_display.set_duration
        )
        self.current_test_executor.armed_state_update.connect(
            self.status_panel.set_armed_state
        )
        self.current_test_executor.mode_update.connect(
            self.status_panel.set_mode
        )
        self.current_test_executor.actuator_feedback_update.connect(
            self.actuator_display.update_feedback
        )

        # IBIT-only signals
        if self.test_mode == 'ibit':
            self.current_test_executor.iteration_update.connect(
                self.progress_widget.set_iteration
            )
            self.current_test_executor.statistics_update.connect(
                self.update_statistics_display
            )
            self.current_test_executor.ibit_state_update.connect(
                self.ibit_display.set_substate
            )

        # Playback-only signals
        if self.test_mode == 'playback':
            self.current_test_executor.progress_update.connect(
                self.ibit_display.set_playback_progress
            )
        
        # Start test
        self.current_test_executor.start()
    
    def on_uut_test_complete(self, success, message):
        """Handle test completion for one UUT"""
        uut = self.uuts[self.current_uut_index]
        
        # Handle failures with retry logic
        if not success and "Batch time expired" not in message:
            uut.consecutive_failures = getattr(uut, 'consecutive_failures', 0) + 1
            
            if uut.consecutive_failures >= 3:
                uut.status = "Failed (3x)"
                self.log(
                    f"⚠ UUT {uut.serial_number} failed 3 times, "
                    f"skipping for rest of batch"
                )
                
                # Disable relay when permanently failing this UUT
                self.log("→ Disabling relay for failed UUT...")
                if self.daq:
                    success_relay, msg = self.daq.set_line(uut.relay_line, False)
                    if success_relay:
                        self.log(f"✓ Relay {uut.relay_line} disabled")
                    else:
                        self.log(f"⚠ Relay disable: {msg}")
            else:
                uut.status = "Retry"
                self.log(
                    f"⚠ UUT {uut.serial_number} failed "
                    f"(attempt {uut.consecutive_failures}/3), will retry"
                )
        else:
            uut.consecutive_failures = 0  # Reset on success
        
        self.log(f"{'✓' if success else '✗'} UUT {uut.serial_number}: {message}")
        self.uut_table_widget.update_table(self.uuts)
        
        if success:
            self.alert_banner.hide()
        
        # Continue testing if time remaining
        if self.testing_active and time.time() < self.batch_end_time:
            # Check if we're moving to a DIFFERENT UUT
            next_uut_index = (self.current_uut_index + 1) % len(self.uuts)
            
            if next_uut_index != self.current_uut_index:
                # Moving to different UUT
                self.log("\n" + "="*60)
                self.log("SWITCHING TO NEXT UUT")
                self.log("="*60)
                self.log(f"✓ Relay already disabled from previous IBIT")
                self.log("="*60 + "\n")
            else:
                # Same UUT, next iteration
                self.log(
                    f"→ Continuing with UUT {uut.serial_number} - "
                    f"Iteration {uut.iterations_completed + 1}"
                )
            
            QTimer.singleShot(2000, self.start_next_uut)
        elif self.testing_active:
            self.batch_complete()
    
    def on_batch_time_expired(self):
        """Handle batch time expiration"""
        self.batch_complete()
    
    def batch_complete(self):
        """Handle batch test completion"""
        self.testing_active = False
        self.elapsed_timer.stop()
        
        # Disable relay for the last UUT
        if 0 <= self.current_uut_index < len(self.uuts):
            uut = self.uuts[self.current_uut_index]
            self.log("\n" + "="*60)
            self.log("BATCH COMPLETE - DISABLING FINAL RELAY")
            self.log("="*60)
            
            if self.daq:
                success_relay, msg = self.daq.set_line(uut.relay_line, False)
                if success_relay:
                    self.log(
                        f"✓ Relay {uut.relay_line} disabled for UUT {uut.serial_number}"
                    )
                else:
                    self.log(f"⚠ Relay disable: {msg}")
            
            self.log("="*60 + "\n")
        
        # Update UUT statuses
        for uut in self.uuts:
            if uut.status == "Testing" or uut.status == "Ready":
                uut.status = "Complete"
        self.uut_table_widget.update_table(self.uuts)
        
        self.log("═══════════════════════════════════════")
        self.log("BATCH TEST COMPLETE")
        self.log(f"End Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self.log("═══════════════════════════════════════")
        
        # Generate report
        self.generate_batch_report()
        
        # Reset UI
        self.control_buttons.set_testing_mode(False)
        self.progress_widget.set_current_uut("Batch Complete")
        self.status_panel.reset()
        self.ibit_display.reset()
        self.actuator_display.reset()
        
        # Show summary
        total_iterations = sum(uut.iterations_completed for uut in self.uuts)
        summary = (
            f"Batch test completed.\n\n"
            f"Total iterations: {total_iterations:,}\n"
            f"Logs saved in: {self.log_directory}"
        )
        QMessageBox.information(self, "Batch Complete", summary)
        
        # Re-enable Windows sleep
        if platform.system() == "Windows":
            try:
                import ctypes
                ES_CONTINUOUS = 0x80000000
                ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
            except:
                pass
    
    def stop_test(self):
        """Stop test gracefully"""
        if QMessageBox.question(
            self,
            "Confirm Stop",
            "Stop the current batch test?\n\n"
            "The current test will complete its cleanup sequence safely.",
            QMessageBox.Yes | QMessageBox.No
        ) == QMessageBox.Yes:
            
            self.log("=" * 60)
            self.log("⚠ STOP REQUESTED - Graceful Shutdown")
            self.log("=" * 60)
            
            # Signal test to stop
            self.testing_active = False
            self.elapsed_timer.stop()
            
            if self.current_test_executor:
                self.log("→ Signaling test executor to stop...")
                self.current_test_executor.stop()
                
                # Update UI
                self.control_buttons.set_enabled(False, False)
                self.progress_widget.set_current_uut(
                    "Stopping... (completing cleanup)"
                )
                QApplication.processEvents()
                
                self.log("  Waiting for test thread to complete cleanup...")
                
                # Wait with progress updates
                wait_start = time.time()
                max_wait = 15.0
                
                while (self.current_test_executor.isRunning() and 
                       (time.time() - wait_start) < max_wait):
                    QApplication.processEvents()
                    time.sleep(0.1)
                    elapsed = time.time() - wait_start
                    if int(elapsed) % 5 == 0 and elapsed > 0:
                        self.log(f"  ... still waiting ({elapsed:.0f}s)")
                
                if not self.current_test_executor.isRunning():
                    self.log("  ✓ Test thread completed cleanup gracefully")
                else:
                    self.log("  ⚠ Test thread did not finish within timeout")
                    self.log("  → Forcing termination...")
                    self.current_test_executor.terminate()
                    self.current_test_executor.wait(2000)
                
                self.current_test_executor = None
            
            # Disable relay after test thread stopped
            if 0 <= self.current_uut_index < len(self.uuts):
                uut = self.uuts[self.current_uut_index]
                self.log("\n" + "="*60)
                self.log("STOP COMPLETE - DISABLING RELAY")
                self.log("="*60)
                
                if self.daq:
                    success_relay, msg = self.daq.set_line(uut.relay_line, False)
                    if success_relay:
                        self.log(f"✓ Relay {uut.relay_line} disabled")
                    else:
                        self.log(f"⚠ Relay disable: {msg}")
                
                self.log("="*60 + "\n")
                
                uut.status = "Stopped"
                self.uut_table_widget.update_table(self.uuts)
            
            # Re-enable controls
            self.control_buttons.set_testing_mode(False)
            
            # Reset UI
            self.progress_widget.set_current_uut("Stopped")
            self.status_panel.reset()
            self.ibit_display.reset()
            self.actuator_display.reset()
            self.alert_banner.hide()
            
            self.log("=" * 60)
            self.log("✓ Test stopped - Cleanup complete")
            self.log("=" * 60)
    
    def emergency_stop(self):
        """Emergency stop - immediately disable all relays"""
        self.log("⚠⚠⚠ EMERGENCY STOP ACTIVATED ⚠⚠⚠")
        
        self.testing_active = False
        
        if self.current_test_executor:
            self.current_test_executor.stop()
        
        if self.daq.do_task:
            self.daq.set_all_low()
            self.log("All relays disabled")
        
        self.elapsed_timer.stop()
        self.control_buttons.set_testing_mode(False)
        self.alert_banner.show_alert("EMERGENCY STOP ACTIVATED")
        
        QMessageBox.warning(
            self,
            "Emergency Stop",
            "Emergency stop activated. All relays disabled."
        )
    
    # ========== UTILITY METHODS ==========
    
    def on_test_mode_changed(self, mode):
        """Update UI elements when test mode radio button changes"""
        self.test_mode = mode
        self.ibit_display.set_mode(mode)
        self.control_buttons.set_test_mode_label(mode)
        self.progress_widget.set_test_mode(mode)
        mode_str = "IBIT" if mode == 'ibit' else "Flight Profile Playback"
        self.setWindowTitle(
            f"Multi-UUT Flight Controller Test System v5.0 — {mode_str}"
        )
        self.update_status_bar()

    def update_elapsed_time(self):
        """Update elapsed/remaining time displays"""
        if self.batch_start_datetime and self.testing_active:
            elapsed = time.time() - self.batch_start_datetime.timestamp()
            remaining = max(0, self.batch_end_time - time.time())
            
            self.progress_widget.set_elapsed(elapsed)
            self.progress_widget.set_remaining(remaining)
            
            # Update progress bar
            if self.batch_end_time > self.batch_start_datetime.timestamp():
                total_duration = self.batch_end_time - self.batch_start_datetime.timestamp()
                progress = int((elapsed / total_duration) * 100)
                self.progress_widget.set_progress(min(100, progress))
    
    def update_statistics_display(self, statistics):
        """Update statistics displays"""
        self.current_statistics = statistics
    
    def show_alert(self, message):
        """Show alert banner"""
        self.alert_banner.show_alert(message)
    
    def generate_batch_report(self):
        """Generate batch test report"""
        mode_tag = 'IBIT' if self.test_mode == 'ibit' else 'Playback'
        report_file = os.path.join(
            self.report_directory,
            f"BatchTest_{mode_tag}_v5.0_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )

        report = {
            'test_type': f'{mode_tag}_v5.0',
            'version': '5.0',
            'test_mode': self.test_mode,
            'batch_start_time': self.batch_start_datetime.strftime('%Y-%m-%d %H:%M:%S'),
            'batch_end_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'total_duration_seconds': time.time() - self.batch_start_datetime.timestamp(),
            'log_directory': self.log_directory,
            'test_config': self.test_config,
            'uuts': []
        }
        
        for uut in self.uuts:
            uut_report = {
                'serial_number': uut.serial_number,
                'ip_address': uut.ip_address,
                'status': uut.status,
                'iterations_completed': uut.iterations_completed,
                'last_log_file': uut.log_file
            }
            report['uuts'].append(uut_report)
        
        try:
            with open(report_file, 'w') as f:
                json.dump(report, f, indent=2)
            self.log(f"✓ Batch report saved: {report_file}")
        except Exception as e:
            self.log(f"✗ Failed to save report: {e}")
    
    def browse_log_directory(self):
        """Let user choose log directory"""
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Log Directory",
            self.log_directory
        )
        
        if directory:
            self.log_directory = directory
            self.test_config_widget.set_log_directory(directory)
            self.update_status_bar()
            self.log(f"Log directory set to: {directory}")
    
    def open_log_directory(self):
        """Open log directory in file explorer"""
        self.open_directory(self.log_directory)
    
    def open_directory(self, directory):
        """Open directory in system file explorer"""
        try:
            if platform.system() == "Windows":
                os.startfile(directory)
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", directory])
            else:
                subprocess.Popen(["xdg-open", directory])
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not open directory: {e}")
    
    def on_log_dir_changed(self, directory):
        """Handle log directory change"""
        self.log_directory = directory
        self.update_status_bar()
    
    def update_status_bar(self):
        """Update status bar"""
        mode_str = "IBIT" if self.test_mode == 'ibit' else "Flight Profile Playback"
        self.statusBar.showMessage(
            f"Mode: {mode_str} | Logs: {self.log_directory} | "
            f"Reports: {self.report_directory} | v5.0"
        )
    
    def log(self, message):
        """Log message to console"""
        self.log_widget.append(message)
    
    def save_settings(self):
        """Save application settings"""
        settings = {
            'log_directory': self.log_directory,
            'report_directory': self.report_directory,
            'test_config': self.test_config
        }
        settings.update(self.test_config_widget.get_all_settings())
        
        settings_file = os.path.join(self.script_dir, "..", "app_settings.json")
        try:
            with open(settings_file, 'w') as f:
                json.dump(settings, f, indent=2)
        except Exception as e:
            self.log(f"⚠ Could not save settings: {e}")
    
    def load_settings(self):
        """Load application settings"""
        settings_file = os.path.join(self.script_dir, "..", "app_settings.json")
        if not os.path.exists(settings_file):
            return
        
        try:
            with open(settings_file, 'r') as f:
                settings = json.load(f)
            
            self.log_directory = settings.get('log_directory', self.log_directory)
            self.report_directory = settings.get('report_directory', self.report_directory)
            
            self.test_config_widget.load_settings(settings)
            
            self.update_status_bar()
            self.log("✓ Settings loaded")
        except Exception as e:
            self.log(f"⚠ Could not load settings: {e}")
    
    def closeEvent(self, event):
        """Handle window close"""
        if self.testing_active:
            reply = QMessageBox.question(
                self,
                "Test Running",
                "A test is currently running. Stop and exit?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                event.ignore()
                return
        
        self.save_settings()
        
        if self.daq:
            self.daq.close()
        
        event.accept()