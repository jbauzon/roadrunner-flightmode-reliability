from __future__ import annotations

"""
Main Window - Roadrunner Flight Test operator console.
"""
import os
import sys
import json
import time
import platform
import subprocess
from datetime import datetime
from typing import Optional

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QMessageBox, QFileDialog, QApplication, QScrollArea, QShortcut,
    QStackedWidget, QPushButton,
)
from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QKeySequence

from hardware.daq import SimpleDAQController
from vehicle.connection import UUT
from vehicle.constants import TestMode, UUTStatus, AlertSeverity, DAQ_HEALTH_CHECK_INTERVAL
from version import __version__
from testing import UUTTestExecutor, PlaybackTestExecutor, BatchWatchdog, ErrorLogger
from testing.debug_connection import DebugConnection
from . import theme as T
from .widgets import (
    HeaderBanner,
    DAQSetupWidget, TestConfigWidget, UUTTableWidget,
    StatusPanelWidget, IBITDisplayWidget, ActuatorFeedbackWidget,
    AlertBannerWidget, ProgressWidget, ControlButtonsWidget,
    LogWidget, AddUUTDialog, DebugConsoleWidget, TelemetryPanelWidget
)
from .qt_adapter import QtExecutorBridge
from .command_server import CommandServer


class MultiUUTTestGUI(QMainWindow):
    """Roadrunner Flight Test operator console — multi-UUT IBIT and Playback."""

    def __init__(self):
        super().__init__()

        # ── Directories ───────────────────────────────────────────────────
        # script_dir is ui/ — project root is one level up
        self.script_dir    = os.path.dirname(os.path.abspath(__file__))
        self.project_root  = os.path.abspath(os.path.join(self.script_dir, ".."))
        self.log_directory = os.path.abspath(os.path.join(self.project_root, "logs"))
        self.report_directory = os.path.abspath(os.path.join(self.project_root, "reports"))
        try:
            os.makedirs(self.log_directory, exist_ok=True)
        except OSError as e:
            import tempfile
            fallback = os.path.join(tempfile.gettempdir(), 'RoadrunnerLogs')
            os.makedirs(fallback, exist_ok=True)
            self.log_directory = fallback
            # Can't log yet (GUI not built), but print to console
            print(f"⚠ Log directory path too long or invalid: {e}")
            print(f"  Using fallback: {fallback}")
        try:
            os.makedirs(self.report_directory, exist_ok=True)
        except OSError as e:
            import tempfile
            fallback = os.path.join(tempfile.gettempdir(), 'RoadrunnerReports')
            os.makedirs(fallback, exist_ok=True)
            self.report_directory = fallback

        # ── Hardware ──────────────────────────────────────────────────────
        self.daq = SimpleDAQController()

        # ── State ─────────────────────────────────────────────────────────
        self.uuts                  = []
        self.current_test_executor = None
        self.current_uut_index     = -1
        self.batch_start_datetime  = None
        self.batch_end_time        = None    # time.monotonic() deadline (C-9)
        self._batch_end_wall       = None    # wall-clock deadline (for display)
        self.testing_active        = False
        self.current_statistics    = None
        self.test_mode             = TestMode.IBIT
        self.playback_csv          = ''
        self.playback_type         = 'Actuation'
        self._watchdog: Optional[BatchWatchdog] = None
        self._starting_uut         = False  # S-5: re-entrancy guard
        self._last_timer_tick      = time.monotonic()  # C-9: hibernation detection

        self.test_config = {
            'ibit_timeout':       300.0,
            'phase_timeout':       90.0,
            'arm_timeout':         60.0,
            'max_arm_iterations':  20,
            'skip_arm_for_ibit':   False,
        }

        self._last_mode            = 0      # tracks last mode int for telemetry panel
        self._debug_conn: Optional[DebugConnection] = None

        # ── Timers ────────────────────────────────────────────────────────
        self.daq_health_timer = QTimer()
        self.elapsed_timer    = QTimer()

        # ── Build UI ──────────────────────────────────────────────────────
        self._init_ui()

        # ── Post-build wiring ─────────────────────────────────────────────
        self.daq_health_timer.timeout.connect(self.check_daq_health)
        self.daq_health_timer.start(DAQ_HEALTH_CHECK_INTERVAL)

        QTimer.singleShot(100, self.load_settings)
        QTimer.singleShot(500, self.detect_daq_devices)
        QTimer.singleShot(200, lambda: self.on_test_mode_changed(
            self.test_config_widget.get_test_mode()
        ))

        # ── Command server ────────────────────────────────────────────────
        self._cmd_server = CommandServer(parent=self)
        self._cmd_server.start(self._handle_remote_command)
        self.log(f"Command server listening on port {CommandServer.DEFAULT_PORT}")

        self.log("")
        self.log("Getting started:")
        self.log("  1. Select DAQ device and click Detect")
        self.log("  2. Click + Add to configure UUTs (serial, IP, port, relay)")
        self.log("  3. Set test duration and click Start IBIT Test")
        self.log("  Shortcuts: Ctrl+S Start | Ctrl+Q Stop | Ctrl+E Emergency | F5 Detect")
        self.log("")

        # ── Keyboard shortcuts ────────────────────────────────────────────
        QShortcut(QKeySequence("Ctrl+S"), self, self.start_all_tests)
        QShortcut(QKeySequence("Ctrl+Q"), self, self.stop_test)
        QShortcut(QKeySequence("Ctrl+E"), self, self.emergency_stop)
        QShortcut(QKeySequence("F5"), self, self.detect_daq_devices)
        QShortcut(QKeySequence("Ctrl+D"), self, self._toggle_debug_console)

    # ═══════════════════════════════════════════════════════════════════════
    # UI construction
    # ═══════════════════════════════════════════════════════════════════════

    def _init_ui(self):
        self.setWindowTitle(f"Roadrunner Flight Test v{__version__}  —  IBIT")
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

        # ── Mode tab bar ──────────────────────────────────────────────────
        mode_bar = QWidget()
        mode_bar.setFixedHeight(40)
        mode_bar.setStyleSheet(
            f"background: {T.BG_ELEVATED}; border-bottom: 1px solid {T.BORDER};"
        )
        mode_bar_layout = QHBoxLayout(mode_bar)
        mode_bar_layout.setContentsMargins(16, 0, 16, 0)
        mode_bar_layout.setSpacing(4)

        self._tab_test  = QPushButton("TEST MODE")
        self._tab_debug = QPushButton("DEBUG MODE")

        for btn in (self._tab_test, self._tab_debug):
            btn.setCheckable(True)
            btn.setFixedHeight(32)
            btn.setFixedWidth(140)
            btn.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {T.TEXT_DISABLED}; "
                f"border: none; border-radius: 4px; font-size: {T.FONT_SIZE_SM}; "
                f"font-weight: bold; letter-spacing: 1px; }}"
                f"QPushButton:checked {{ background: {T.BG_SURFACE}; color: {T.TEXT_PRIMARY}; "
                f"border-bottom: 2px solid {T.GREEN}; }}"
                f"QPushButton:hover:!checked {{ color: {T.TEXT_SECONDARY}; }}"
            )

        self._tab_test.setChecked(True)
        self._tab_test.clicked.connect(lambda: self._switch_mode(0))
        self._tab_debug.clicked.connect(lambda: self._switch_mode(1))

        mode_bar_layout.addWidget(self._tab_test)
        mode_bar_layout.addWidget(self._tab_debug)
        mode_bar_layout.addStretch()
        root_layout.addWidget(mode_bar)

        # ── Main area: left column + stacked content ──────────────────────
        main_splitter = QSplitter(Qt.Horizontal)
        main_splitter.setHandleWidth(2)
        main_splitter.setStyleSheet(
            f"QSplitter::handle {{ background: {T.BORDER}; }}"
        )
        root_layout.addWidget(main_splitter, 1)

        # ── Left column (shared — always visible) ─────────────────────
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
        main_splitter.addWidget(left_scroll)

        # ── Stacked content area ───────────────────────────────────────
        self._content_stack = QStackedWidget()
        main_splitter.addWidget(self._content_stack)
        main_splitter.setSizes([340, 1460])

        # ── Page 0: TEST MODE — existing centre + right columns ───────
        test_page = QSplitter(Qt.Horizontal)
        test_page.setHandleWidth(2)
        test_page.setStyleSheet(
            f"QSplitter::handle {{ background: {T.BORDER}; }}"
        )

        # Centre column
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
        test_page.addWidget(centre_panel)

        # Right column
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
        test_page.addWidget(right_scroll)

        test_page.setSizes([820, 540])
        self._content_stack.addWidget(test_page)   # index 0

        # ── Page 1: DEBUG MODE — commands | telemetry ─────────────────
        debug_page = QWidget()
        debug_layout = QHBoxLayout(debug_page)
        debug_layout.setContentsMargins(0, 0, 0, 0)
        debug_layout.setSpacing(0)

        # Debug commands (left half)
        debug_cmd_scroll = QScrollArea()
        debug_cmd_scroll.setWidgetResizable(True)
        debug_cmd_scroll.setFrameShape(0)
        debug_cmd_scroll.setStyleSheet(
            f"background: {T.BG_BASE}; border-right: 1px solid {T.BORDER};"
        )
        self.debug_console = DebugConsoleWidget()
        self.debug_console.command_sent.connect(
            lambda msg: self.log(f"[DEBUG] {msg}")
        )
        self.debug_console.connect_requested.connect(self._debug_connect)
        self.debug_console.disconnect_requested.connect(self._debug_disconnect)
        debug_cmd_scroll.setWidget(self.debug_console)

        # Live telemetry (right half)
        self.telemetry_panel = TelemetryPanelWidget()

        debug_cmd_scroll.setMaximumWidth(500)
        debug_cmd_scroll.setMinimumWidth(440)
        debug_layout.addWidget(debug_cmd_scroll, 0)   # fixed width
        debug_layout.addWidget(self.telemetry_panel, 1)  # stretches
        self._content_stack.addWidget(debug_page)  # index 1

        # Populate debug console with any already-configured UUTs (initially empty)
        self.debug_console.populate_uuts(self.uuts)

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
        self.daq_widget.sitl_clicked.connect(self.launch_sitl)

        self.test_config_widget.log_dir_changed.connect(self.on_log_dir_changed)
        self.test_config_widget.browse_clicked.connect(self.browse_log_directory)
        self.test_config_widget.open_clicked.connect(self.open_log_directory)
        self.test_config_widget.mode_changed.connect(self.on_test_mode_changed)

        self.uut_table_widget.add_clicked.connect(self.add_uut)
        self.uut_table_widget.edit_clicked.connect(self.edit_uut)
        self.uut_table_widget.remove_clicked.connect(self.remove_uut)
        self.uut_table_widget.save_clicked.connect(self.save_uut_config)
        self.uut_table_widget.load_clicked.connect(self.load_uut_config)
        self.uut_table_widget.table.selectionModel().selectionChanged.connect(
            self._on_uut_selection_changed
        )

        self.control_buttons.start_clicked.connect(self.start_all_tests)
        self.control_buttons.stop_clicked.connect(self.stop_test)
        self.control_buttons.emergency_clicked.connect(self.emergency_stop)

        self.elapsed_timer.timeout.connect(self.update_elapsed_time)

    def _switch_mode(self, index: int) -> None:
        """Switch between Test (0) and Debug (1) mode tabs."""
        self._content_stack.setCurrentIndex(index)
        self._tab_test.setChecked(index == 0)
        self._tab_debug.setChecked(index == 1)

        if index == 1:
            self.log("Switched to Debug Mode — commands bypass all safety checks")
        else:
            self.log("Switched to Test Mode")

    def _toggle_debug_console(self) -> None:
        """Ctrl+D: switch to debug mode tab."""
        self._switch_mode(1)
        self._tab_debug.setChecked(True)
        self._tab_test.setChecked(False)

    def _debug_connect(self, serial: str, ip: str, port: int) -> None:
        """Connect to a UUT from Debug Mode without starting a test."""
        if self._debug_conn:
            self._debug_disconnect()

        self._debug_conn = DebugConnection(ip, port, serial)
        self._debug_conn.on_log = self.log
        self._debug_conn.on_error = lambda msg: self.show_alert(msg, severity=AlertSeverity.ERROR)

        # Wire incoming messages to telemetry panel
        def _on_message(msg):
            msg_type = msg.get_type()
            try:
                from vehicle.constants import MsgType
                if msg_type == MsgType.ACTUATION_SYS_STATUS:
                    from testing.helpers import _build_actuator_feedback_dict
                    from vehicle.constants import safe_int_field
                    self.telemetry_panel.update_actuator_feedback(
                        _build_actuator_feedback_dict(msg)
                    )
                    mode = safe_int_field(msg, 'actuation_state')
                    self.telemetry_panel.update_vehicle_status(mode, 0, False)
                elif msg_type == MsgType.PANDION_STATUS:
                    from vehicle.constants import safe_int_field, is_armed
                    regime = safe_int_field(msg, 'flight_regime', 255)
                    armed = is_armed(regime)
                    mode = getattr(self, '_last_mode', 0)
                    self.telemetry_panel.update_vehicle_status(mode, regime, armed)
                elif msg_type == MsgType.ENGINE_STATUS:
                    self.telemetry_panel.update_engine(
                        getattr(msg, 'eng_1_speed', 0) or 0,
                        getattr(msg, 'eng_1_egt_temp_degC', 0) or 0,
                        getattr(msg, 'eng_1_fuel_pump_curr_mA', 0) or 0,
                    )
                # Add to message stream
                key_fields = []
                for field in ('actuation_state', 'flight_regime', 'eng_1_speed'):
                    val = getattr(msg, field, None)
                    if val is not None:
                        key_fields.append(f"{field}={val}")
                summary = ', '.join(key_fields[:2]) if key_fields else ''
                self.telemetry_panel.add_message(msg_type, summary)
            except Exception:
                pass

        self._debug_conn.on_message = _on_message

        def _on_connected(serial):
            # Give debug console the connection
            self.debug_console.set_connection(
                self._debug_conn.master,
                self._debug_conn.master_lock,
                serial,
            )
            self.telemetry_panel.reset()

        self._debug_conn.on_connected = _on_connected
        self._debug_conn.on_disconnected = lambda s: self.debug_console.clear_connection()

        # Connect in background thread so UI doesn't freeze
        import threading as _threading
        _threading.Thread(
            target=self._debug_conn.connect, daemon=True, name='debug-connect'
        ).start()

    def _debug_disconnect(self) -> None:
        """Disconnect from the current debug connection."""
        if self._debug_conn:
            import threading as _threading
            _threading.Thread(
                target=self._debug_conn.disconnect, daemon=True
            ).start()
            self._debug_conn = None
        self.telemetry_panel.reset()

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

    def launch_sitl(self):
        """Start SITL simulation mode from within the GUI.

        Everything blocking runs on a daemon thread — the UI stays responsive.
        Results are handed back to the Qt main thread via QTimer.singleShot(0).
        """
        import threading, time
        from sim.vehicle import PandionVehicleSim
        from sim.mock_daq import MockDAQController
        from vehicle.connection import UUT
        import vehicle.connection as conn_mod

        self.log("="*56)
        self.log("  LAUNCHING SITL SIMULATION")
        self.log("="*56)

        # Disable button immediately so operator can't double-click
        self.daq_widget.sitl_btn.setEnabled(False)
        self.daq_widget.sitl_btn.setText("Starting...")

        sim_configs = [
            {'serial': 'RR-SIM-001', 'port': 19901, 'relay': 0,
             'ibit_pass': True,  'sysid': 1},
            {'serial': 'RR-SIM-002', 'port': 19902, 'relay': 1,
             'ibit_pass': False, 'mistracking_flags': 0xC0, 'sysid': 2},
        ]

        # Patch connection for loopback now (on main thread — fast, no sleep)
        _HERE = os.path.dirname(os.path.abspath(__file__))
        _ROOT = os.path.abspath(os.path.join(_HERE, ".."))
        dialect_dir = os.path.join(_ROOT, "vehicle", "dialects")

        def _sitl_connect(ip_address, port, timeout=10.0):
            if dialect_dir not in sys.path:
                sys.path.insert(0, dialect_dir)
            from pymavlink import mavutil
            m = mavutil.mavlink_connection(
                f"udpout:{ip_address}:{port}",
                dialect="pandion_vehicle_roadrunner",
                source_system=255, source_component=190,
            )
            for _ in range(5):
                try:
                    m.mav.heartbeat_send(
                        mavutil.mavlink.MAV_TYPE_GCS,
                        mavutil.mavlink.MAV_AUTOPILOT_INVALID,
                        0, 0, mavutil.mavlink.MAV_STATE_ACTIVE)
                except OSError:
                    pass
                hb = m.recv_match(type='HEARTBEAT', blocking=True, timeout=1.0)
                if hb and hb.get_srcSystem() != 255:
                    return m
            raise Exception(f"SITL vehicle not responding on {ip_address}:{port}")

        conn_mod.connect_to_vehicle = _sitl_connect

        def _on_ready(mock_daq):
            """Called on Qt main thread after sims have booted."""
            self.daq = mock_daq

            # Pre-load UUTs
            self.uuts = []
            for cfg in sim_configs:
                self.uuts.append(
                    UUT(cfg['serial'], '127.0.0.1', cfg['port'], cfg['relay'])
                )
            self.uut_table_widget.update_table(self.uuts)
            self.debug_console.populate_uuts(self.uuts)

            self.daq_widget.set_sitl_active()
            self.log("  MockDAQ initialized, UUTs loaded")
            self.log("  SITL ready — click Connect in Debug Mode or Start to test")
            self.log("  (RR-SIM-001: PASS  ·  RR-SIM-002: FAIL — elevon mistracking)")
            self.log("="*56)

        def _background():
            """Boot sims and build MockDAQ — runs entirely off the main thread."""
            sims = []
            for cfg in sim_configs:
                sim = PandionVehicleSim(
                    vehicle_port=cfg['port'],
                    sysid=cfg['sysid'],
                    ibit_pass=cfg['ibit_pass'],
                    mistracking_flags=cfg.get('mistracking_flags', 0),
                    boot_time_s=2.0,
                    ibit_duration_scale=0.5,
                    boot_monitors=[0, 1, 2, 3],
                )
                threading.Thread(target=sim.start, daemon=True,
                                 name=f"sitl-{cfg['port']}").start()
                sims.append(sim)
                QTimer.singleShot(0, lambda s=cfg['serial'], p=cfg['port'],
                                  ok=cfg['ibit_pass']:
                    self.log(f"  Started {s} on port {p} "
                             f"({'PASS' if ok else 'FAIL'})"))

            self._sitl_sims = sims

            # Wait for sims to boot off the main thread — UI stays live
            time.sleep(2.5)

            mock_daq = MockDAQController()
            mock_daq.initialize('SimDAQ/SITL')
            for i, cfg in enumerate(sim_configs):
                mock_daq.register_vehicle(cfg['relay'], sims[i])

            # Hand results back to the Qt main thread
            QTimer.singleShot(0, lambda: _on_ready(mock_daq))

        threading.Thread(target=_background, daemon=True,
                         name='sitl-launcher').start()

    def check_daq_health(self):
        if not self.daq or not self.daq.do_task:
            return

        if not self.testing_active:
            return

        if not self.daq.verify_connection():
            try:
                self.daq.reconnect()
                if not self.daq.verify_connection():
                    # Reconnect failed — force all relays off before stopping
                    self.log("⚠ DAQ connection lost — forcing all relays OFF")
                    try:
                        self.daq.set_all_low()
                        self.log("✓ All relays disabled (DAQ reconnect failed)")
                    except Exception as relay_err:
                        self.log(f"✗ Relay force-off failed: {relay_err}")
                        self.alert_banner.show_alert(
                            "DAQ DISCONNECTED AND RELAY FORCE-OFF FAILED. "
                            "Manually disconnect all vehicle power immediately.",
                            severity=AlertSeverity.CRITICAL
                        )
                    self.stop_test()
                    QMessageBox.critical(
                        self, "DAQ Connection Lost",
                        "The NI-DAQmx device is no longer responding.\n"
                        "All relays have been set to OFF.\n"
                        "The test has been stopped.\n\n"
                        "Reconnect the DAQ device and restart to continue."
                    )
                else:
                    self.log("✓ DAQ reconnected successfully")
            except Exception as e:
                self.log(f"⚠ DAQ health check error: {e}")

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
            # Check for duplicate IP:port
            endpoint_conflicts = [u for u in self.uuts if u.ip_address == uut.ip_address and u.port == uut.port]
            if endpoint_conflicts:
                QMessageBox.critical(
                    self, "Configuration Error",
                    f"UUT {endpoint_conflicts[0].serial_number} already uses "
                    f"{uut.ip_address}:{uut.port}.\n\nDuplicate IP:port will cause message "
                    f"interleaving and false PASS results."
                )
                return
            self.uuts.append(uut)
            self.uut_table_widget.update_table(self.uuts)
            self.debug_console.populate_uuts(self.uuts)
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
            # Validate relay line range
            if self.daq.do_task and not (0 <= updated.relay_line < self.daq.num_lines):
                QMessageBox.warning(
                    self, "Invalid Relay Line",
                    f"Relay line {updated.relay_line} is out of range "
                    f"(0–{self.daq.num_lines - 1} available)."
                )
                return
            # Check for duplicate IP:port (excluding the row being edited)
            endpoint_conflicts = [
                u for i, u in enumerate(self.uuts)
                if i != row and u.ip_address == updated.ip_address and u.port == updated.port
            ]
            if endpoint_conflicts:
                QMessageBox.critical(
                    self, "Configuration Error",
                    f"UUT {endpoint_conflicts[0].serial_number} already uses "
                    f"{updated.ip_address}:{updated.port}.\n\nDuplicate IP:port will cause message "
                    f"interleaving and false PASS results."
                )
                return
            self.uuts[row] = updated
            self.uut_table_widget.update_table(self.uuts)
            self.debug_console.populate_uuts(self.uuts)
            self.log(f"✓ Updated UUT {updated.serial_number}")

    def remove_uut(self):
        if self.testing_active:
            QMessageBox.warning(self, "Test Running",
                "Cannot remove a UUT while testing is active.\nStop the test first.")
            return
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
            self.debug_console.populate_uuts(self.uuts)
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

    def _on_uut_selection_changed(self):
        """Show cached actuator feedback for the selected UUT."""
        row = self.uut_table_widget.get_selected_row()
        if 0 <= row < len(self.uuts):
            self.actuator_display.set_current_uut(self.uuts[row].serial_number)

    # ═══════════════════════════════════════════════════════════════════════
    # Test control
    # ═══════════════════════════════════════════════════════════════════════

    def start_all_tests(self):
        # Guard against double-click Start
        if self.testing_active:
            return

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

        if test_mode == TestMode.PLAYBACK and not playback_csv:
            QMessageBox.warning(self, "No Profile",
                "Select a flight profile CSV before starting Playback mode.")
            return
        if test_mode == TestMode.PLAYBACK and not os.path.isfile(playback_csv):
            QMessageBox.warning(self, "Profile Not Found",
                f"The CSV file no longer exists:\n{playback_csv}\n\n"
                "Please re-select the file.")
            return

        mode_label = (
            "IBIT Test" if test_mode == TestMode.IBIT
            else f"Flight Profile Playback  ({playback_type})"
        )

        # Check for relay conflicts
        relay_lines = [u.relay_line for u in self.uuts]
        if len(relay_lines) != len(set(relay_lines)):
            QMessageBox.warning(self, "Relay Conflict",
                "Two or more UUTs share the same relay line.\n"
                "Each UUT must have a unique relay line.")
            return

        # Check for duplicate IP:port combinations
        seen_endpoints = {}
        for uut in self.uuts:
            endpoint = (uut.ip_address, uut.port)
            if endpoint in seen_endpoints:
                QMessageBox.critical(
                    self, "Configuration Error",
                    f"UUTs {seen_endpoints[endpoint]} and {uut.serial_number} share the same "
                    f"IP:port ({uut.ip_address}:{uut.port}).\n\nThis will cause message interleaving "
                    f"and false PASS results. Fix the configuration before testing."
                )
                return
            seen_endpoints[endpoint] = uut.serial_number

        if QMessageBox.question(
            self, "Confirm Start",
            f"Start  {mode_label}\n"
            f"Duration:  {duration_value} {unit}\n"
            f"UUTs:  {len(self.uuts)}\n\n"
            f"Logs → {self.log_directory}",
            QMessageBox.Yes | QMessageBox.No
        ) != QMessageBox.Yes:
            return

        # Atomically set testing_active BEFORE spawning any executors
        self.testing_active = True
        self.control_buttons.set_testing_mode(True)

        # Reset
        for uut in self.uuts:
            uut.status = UUTStatus.READY
            uut.iterations_completed = 0
            uut.consecutive_failures = 0  # S-8: reset on batch restart
            uut.soft_failures = 0         # C-2: reset soft failure count on restart
        self.uut_table_widget.update_table(self.uuts)

        self.batch_start_datetime = datetime.now()
        # C-9: use monotonic clock for deadline — immune to system-clock changes
        self.batch_end_time    = time.monotonic() + duration_seconds
        self._batch_end_wall   = self.batch_start_datetime.timestamp() + duration_seconds
        self._last_timer_tick  = time.monotonic()
        self.current_uut_index    = -1
        self.test_mode            = test_mode
        self.playback_csv         = playback_csv
        self.playback_type        = playback_type

        self.test_config.update(self.test_config_widget.get_config())
        self._test_temperature_c = self.test_config.get('test_temperature_c', None)
        self.alert_banner.hide()

        self.log("═" * 56)
        self.log(f"  BATCH START  —  {mode_label}")
        self.log(f"  {self.batch_start_datetime.strftime('%Y-%m-%d %H:%M:%S')}  "
                 f"Duration: {duration_value} {unit}")
        self.log("═" * 56)

        self._watchdog = BatchWatchdog(
            uuts=self.uuts,
            daq=self.daq,
            log_directory=self.log_directory,
            on_alert=lambda msg: self.show_alert(msg, severity=AlertSeverity.WARNING),
            on_log=self.log,
            is_testing=lambda: self.testing_active,
            current_uut_index=lambda: self.current_uut_index,
        )
        self._watchdog.start()

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
        # S-5: prevent re-entrant calls (e.g. double-fired QTimer.singleShot)
        if getattr(self, '_starting_uut', False):
            return
        self._starting_uut = True
        try:
            self._start_next_uut_impl()
        finally:
            self._starting_uut = False

    def _start_next_uut_impl(self):
        if not self.testing_active:
            return  # Guard against stale QTimer callbacks after stop

        if time.monotonic() >= self.batch_end_time:
            self.batch_complete()
            return

        # C-6: Check if ALL UUTs are permanently failed
        active = [u for u in self.uuts if u.status != UUTStatus.FAILED_PERMANENT]
        if not active:
            self.log("\u26a0 All UUTs permanently failed \u2014 ending batch early")
            self.batch_complete()
            return

        self.current_uut_index = (self.current_uut_index + 1) % len(self.uuts)
        uut = self.uuts[self.current_uut_index]

        if not hasattr(uut, 'consecutive_failures'):
            uut.consecutive_failures = 0

        if uut.status == UUTStatus.FAILED_PERMANENT:
            self.log(f"  Skipping {uut.serial_number} (permanently failed)")
            QTimer.singleShot(100, self.start_next_uut)
            return

        uut.status = UUTStatus.TESTING
        self.uut_table_widget.update_table(self.uuts)
        self.actuator_display.set_current_uut(uut.serial_number)
        self.progress_widget.set_current_uut(
            f"UUT {self.current_uut_index+1}/{len(self.uuts)}  —  {uut.serial_number}"
        )

        # Add log divider so operator can easily find each UUT's test start
        self.log("─" * 56)
        self.log(f"  UUT {self.current_uut_index+1}/{len(self.uuts)}: {uut.serial_number}")
        self.log("─" * 56)

        skip = self.test_config_widget.get_skip_state_management()

        # Create Qt bridge for thread-safe signal dispatch
        self._executor_bridge = QtExecutorBridge(parent=self)
        bridge = self._executor_bridge

        if self.test_mode == TestMode.PLAYBACK:
            self.current_test_executor = PlaybackTestExecutor(
                uut, self.daq, self.batch_end_time,
                self.test_config_widget.get_stabilization_delay(),
                self.test_config_widget.get_connection_timeout(),
                self.log_directory, self.batch_start_datetime,
                playback_csv=self.playback_csv,
                playback_type=self.playback_type,
                config=self.test_config,
                callbacks=bridge.callbacks,
            )
        else:
            self.current_test_executor = UUTTestExecutor(
                uut, self.daq, self.batch_end_time,
                self.test_config_widget.get_stabilization_delay(),
                self.test_config_widget.get_connection_timeout(),
                self.log_directory, self.batch_start_datetime,
                skip_state_management=skip,
                config=self.test_config,
                callbacks=bridge.callbacks,
            )

        # Wire bridge signals to GUI handlers
        bridge.sig_complete.connect(self.on_uut_test_complete)
        bridge.sig_time_expired.connect(self.on_batch_time_expired)
        bridge.sig_log.connect(self.log)
        bridge.sig_connection_health.connect(self.status_panel.set_connection_health)
        bridge.sig_alert.connect(self.show_alert)
        bridge.sig_test_duration.connect(self.ibit_display.set_duration)
        bridge.sig_armed_state.connect(self.status_panel.set_armed_state)
        bridge.sig_mode.connect(self.status_panel.set_mode)
        bridge.sig_actuator_feedback.connect(self.actuator_display.update_feedback)
        bridge.sig_status.connect(self._on_prep_status)
        bridge.sig_relay_state.connect(self.status_panel.set_relay_state)
        bridge.sig_mistracking_update.connect(self.actuator_display.highlight_mistracking)

        if self.test_mode == TestMode.IBIT:
            bridge.sig_iteration.connect(self.progress_widget.set_iteration)
            bridge.sig_statistics.connect(self._on_statistics)
            bridge.sig_ibit_state.connect(self.ibit_display.set_substate)
        else:
            bridge.sig_progress.connect(self.ibit_display.set_playback_progress)

        # ── Wire signals to telemetry panel (active in debug mode) ────────
        def _update_mode(m):
            self._last_mode = m
        bridge.sig_mode.connect(_update_mode)
        bridge.sig_mode.connect(
            lambda m: self.telemetry_panel.update_vehicle_status(
                m, self._last_regime if hasattr(self, '_last_regime') else 0,
                self._last_armed if hasattr(self, '_last_armed') else False)
        )
        bridge.sig_armed_state.connect(
            lambda armed, regime: (
                setattr(self, '_last_armed', armed),
                setattr(self, '_last_regime', regime),
                self.telemetry_panel.update_vehicle_status(self._last_mode, regime, armed),
            )
        )
        bridge.sig_relay_state.connect(self.telemetry_panel.update_relay_state)
        bridge.sig_actuator_feedback.connect(self.telemetry_panel.update_actuator_feedback)
        bridge.sig_ibit_state.connect(self.telemetry_panel.update_ibit_state)
        bridge.sig_mistracking_update.connect(self.telemetry_panel.update_mistracking)

        self.current_test_executor.start()
        self.debug_console.set_test_active(True)

        # Give debug console access to the active connection
        # (executor thread updates it after connecting)
        def _update_debug_connection():
            if hasattr(self.current_test_executor, 'master') and self.current_test_executor.master:
                self.debug_console.set_connection(
                    self.current_test_executor.master,
                    self.current_test_executor.master_lock,
                    uut.serial_number,
                )
        bridge.sig_connection_health.connect(
            lambda h: _update_debug_connection() if h else self.debug_console.clear_connection()
        )

    def on_uut_test_complete(self, success, message):
        uut = self.uuts[self.current_uut_index]

        # Check if this was a soft failure (doesn't count toward permanent skip)
        is_soft_failure = message.startswith('[SOFT]')
        display_message = message.replace('[SOFT] ', '', 1)

        if not success and "Batch time expired" not in message:
            if is_soft_failure:
                # C-2: Soft failure — track separately with a cap of 6
                uut.soft_failures = getattr(uut, 'soft_failures', 0) + 1
                uut.status = UUTStatus.RETRY
                self.log(
                    f"\u26a0 {uut.serial_number} soft failure "
                    f"({uut.soft_failures}/6) \u2014 auto-recovery applied"
                )
                if uut.soft_failures >= 6:
                    uut.status = UUTStatus.FAILED_PERMANENT
                    self.log(
                        f"\u2717 {uut.serial_number} soft-failed {uut.soft_failures}\u00d7 "
                        f"\u2014 permanently skipping "
                        f"(likely persistent infrastructure problem)"
                    )
                    err_log = ErrorLogger(self.log_directory)
                    err_log.error(
                        'SYSTEM', uut.serial_number, uut.iterations_completed,
                        f'UUT permanently skipped after {uut.soft_failures} soft failures',
                        {'soft_failures': uut.soft_failures},
                    )
            else:
                uut.consecutive_failures = getattr(uut, 'consecutive_failures', 0) + 1
                if uut.consecutive_failures >= 3:
                    uut.status = UUTStatus.FAILED_PERMANENT
                    self.log(f"\u26a0 {uut.serial_number} failed 3\u00d7 \u2014 permanently skipping")
                    if self.daq:
                        ok, msg = self.daq.set_line(uut.relay_line, False)
                        self.log(f"  Relay D{uut.relay_line} {'disabled' if ok else 'ERROR: ' + msg}")
                    # Log to error JSONL — permanent failure is a significant event
                    err_log = ErrorLogger(self.log_directory)
                    err_log.error(
                        'IBIT',
                        uut.serial_number,
                        uut.iterations_completed,
                        f'UUT permanently failed after 3 consecutive failures \u2014 skipping for remainder of batch',
                        {'consecutive_failures': uut.consecutive_failures},
                    )
                else:
                    uut.status = UUTStatus.RETRY
                    self.log(
                        f"\u26a0 {uut.serial_number} failed "
                        f"({uut.consecutive_failures}/3) \u2014 will retry"
                    )
        else:
            uut.consecutive_failures = 0
            if success:
                uut.status = UUTStatus.COMPLETE

        self.log(f"{'✓' if success else '✗'}  {uut.serial_number}: {display_message}")
        self.uut_table_widget.update_table(self.uuts)
        self.actuator_display.clear_mistracking_highlights()
        self.debug_console.clear_connection()
        self.debug_console.set_test_active(False)

        if success:
            self.alert_banner.hide()

        # C-9: use monotonic clock for batch deadline comparison
        if self.testing_active and time.monotonic() < self.batch_end_time:
            QTimer.singleShot(2000, self.start_next_uut)
        elif self.testing_active:
            self.batch_complete()

    def on_batch_time_expired(self):
        self.log("⏱ Batch time expired — waiting for current test to complete safely")
        self.show_alert(
            "Batch time expired — completing current test then stopping",
            severity=AlertSeverity.INFO,
        )
        # Don't call batch_complete() here — the executor's finally block will clean up
        # and then call on_uut_test_complete which will detect expired time and call batch_complete
        if self.current_test_executor:
            self.current_test_executor.stop()

    def batch_complete(self):
        self.testing_active = False
        self.elapsed_timer.stop()

        if self._watchdog:
            self._watchdog.stop()
            self._watchdog = None

        if 0 <= self.current_uut_index < len(self.uuts):
            uut = self.uuts[self.current_uut_index]
            if self.daq:
                ok, msg = self.daq.set_line(uut.relay_line, False)
                self.log(f"  Final relay D{uut.relay_line} {'disabled' if ok else 'ERROR: '+msg}")

        for uut in self.uuts:
            if uut.status in (UUTStatus.TESTING, UUTStatus.READY):
                uut.status = UUTStatus.COMPLETE
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
        self.telemetry_panel.reset()

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
            while self.current_test_executor.is_alive() and time.time()-wait_start < 15:
                QApplication.processEvents()
                time.sleep(0.1)

            if not self.current_test_executor.is_alive():
                self.log("✓ Test thread stopped cleanly")
            else:
                self.log("⚠ Thread did not stop within timeout — abandoning")
            self.current_test_executor = None

        if 0 <= self.current_uut_index < len(self.uuts):
            uut = self.uuts[self.current_uut_index]
            if self.daq:
                ok, msg = self.daq.set_line(uut.relay_line, False)
                self.log(f"  Relay D{uut.relay_line} {'disabled' if ok else 'ERROR: '+msg}")
            uut.status = UUTStatus.STOPPED
            self.uut_table_widget.update_table(self.uuts)

        self.control_buttons.set_testing_mode(False)
        self.progress_widget.set_current_uut("Stopped")
        self.status_panel.reset()
        self.ibit_display.reset()
        self.actuator_display.reset()
        self.telemetry_panel.reset()
        self.alert_banner.hide()
        self.log("✓ Stop complete")

    def emergency_stop(self):
        self.log("⚠⚠⚠ EMERGENCY STOP")
        self.testing_active = False
        if self._watchdog:
            self._watchdog.stop()
            self._watchdog = None
        if self.current_test_executor:
            self.current_test_executor.stop()
        if self.daq.do_task:
            self.daq.set_all_low()
            self.log("  All relays disabled")
        self.elapsed_timer.stop()
        self.control_buttons.set_testing_mode(False)
        self.alert_banner.show_alert(
            "EMERGENCY STOP — All relays disabled", severity=AlertSeverity.CRITICAL
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
        if self.testing_active:
            # Don't allow mode switch during an active batch — revert and warn
            self.log("⚠ Cannot switch test mode during an active batch")
            return
        self.test_mode = mode
        self.ibit_display.set_mode(mode)
        self.control_buttons.set_test_mode_label(mode)
        self.progress_widget.set_test_mode(mode)
        self.header.set_mode(mode)
        mode_str = "IBIT" if mode == TestMode.IBIT else "Flight Profile Playback"
        self.setWindowTitle(f"Roadrunner Flight Test v{__version__}  —  {mode_str}")
        self.update_status_bar()

    def update_elapsed_time(self):
        if self.batch_start_datetime and self.testing_active:
            # C-9: hibernation detection — if timer fired late by >5s, system may
            # have suspended/hibernated and the monotonic deadline drifted too far.
            now = time.monotonic()
            tick_gap = now - self._last_timer_tick
            if tick_gap > 5.0:
                self.log(
                    f"\u26a0 Timer gap of {tick_gap:.0f}s detected \u2014 system may have hibernated. "
                    f"Batch deadline adjusted."
                )
                # Extend monotonic batch deadline by the hibernation gap
                self.batch_end_time += tick_gap - 1.0
            self._last_timer_tick = now

            # Compute elapsed/remaining using wall clock for display accuracy
            elapsed   = time.time() - self.batch_start_datetime.timestamp()
            remaining = max(0, self._batch_end_wall - time.time()) if self._batch_end_wall else 0
            self.progress_widget.set_elapsed(elapsed)
            self.progress_widget.set_remaining(remaining)
            total = (self._batch_end_wall - self.batch_start_datetime.timestamp()
                     if self._batch_end_wall else 1)
            self.progress_widget.set_progress(min(100, int(elapsed / max(total, 1) * 100)))

    def _on_statistics(self, statistics):
        self.current_statistics = statistics

    def _on_prep_status(self, status_text):
        """Show preparation phase progress in the Test Status widget."""
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
        elif 'cleanup' in text.lower() or 'restor' in text.lower():
            self.ibit_display.set_substate('RESTORING STATE')
        elif 'OPERATE' in text:
            self.ibit_display.set_substate('OPERATE')
        elif 'DISARM' in text or 'disarm' in text:
            self.ibit_display.set_substate('DISARMING')
        elif 'Stopping' in text or 'stop' in text.lower():
            self.ibit_display.set_substate('STOPPING')

    def show_alert(self, message, severity=None):
        if severity is None:
            severity = AlertSeverity.CRITICAL if 'CRITICAL' in message.upper() else AlertSeverity.WARNING
        self.alert_banner.show_alert(message, severity=severity)

    def generate_batch_report(self):
        tag  = 'IBIT' if self.test_mode == TestMode.IBIT else 'Playback'
        path = os.path.join(
            self.report_directory,
            f"BatchTest_{tag}_v{__version__}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        report = {
            'test_type':   f'{tag}_v{__version__}',
            'version':     __version__,
            'test_mode':   str(self.test_mode),       # TestMode enum → string
            'start':       self.batch_start_datetime.strftime('%Y-%m-%d %H:%M:%S'),
            'end':         datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'duration_s':  time.time() - self.batch_start_datetime.timestamp(),
            'log_dir':     self.log_directory,
            'test_config': self.test_config,
            'test_temperature_c': getattr(self, '_test_temperature_c', None),
            'test_environment': 'thermal_chamber' if getattr(self, '_test_temperature_c', None) is not None else 'ambient',
            'uuts': [{
                'serial':     u.serial_number,
                'ip':         u.ip_address,
                'status':     str(u.status),          # UUTStatus enum → string
                'iterations': u.iterations_completed,
                'log_file':   getattr(u, 'log_file', ''),
            } for u in self.uuts],
        }
        try:
            with open(path, 'w') as f:
                json.dump(report, f, indent=2, default=str)
            self.log(f"✓ Report saved: {path}")
            self.alert_banner.show_alert(
                f"Batch report saved: {os.path.basename(path)}",
                severity=AlertSeverity.INFO, auto_hide_ms=15000
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
        mode_str = "IBIT" if self.test_mode == TestMode.IBIT else "Playback"
        self.statusBar.showMessage(
            f"Mode: {mode_str}   |   Logs: {self.log_directory}   |   v{__version__}"
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
    # Remote command handler (called by CommandServer on GUI thread)
    # ═══════════════════════════════════════════════════════════════════════

    def _handle_remote_command(self, cmd, args):
        """
        Handle a remote command and return a response dict.

        Called on the GUI thread by CommandServer._dispatch().
        """
        if cmd == 'start':
            self._auto_start_test(int(args.get('seconds', 120)))
            return {'ok': True, 'msg': 'Test started'}

        elif cmd == 'stop':
            self.testing_active = False
            if self.current_test_executor:
                self.current_test_executor.stop()
            return {'ok': True, 'msg': 'Stop requested'}

        elif cmd == 'emergency':
            self.emergency_stop()
            return {'ok': True, 'msg': 'Emergency stop'}

        elif cmd == 'status':
            uut_statuses = [
                {'serial': u.serial_number, 'status': u.status,
                 'iterations': u.iterations_completed}
                for u in self.uuts
            ]
            return {
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
            return {'ok': True, 'path': path,
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
            return {'ok': True, 'seconds': secs}

        else:
            return {'error': f'Unknown command: {cmd}'}

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
            uut.status = UUTStatus.READY
            uut.iterations_completed = 0
            uut.soft_failures = 0
        self.uut_table_widget.update_table(self.uuts)

        self.testing_active = True
        self.batch_start_datetime = datetime.now()
        # C-9: use monotonic clock for batch deadline
        self.batch_end_time    = time.monotonic() + duration_seconds
        self._batch_end_wall   = self.batch_start_datetime.timestamp() + duration_seconds
        self._last_timer_tick  = time.monotonic()
        self.current_uut_index = -1
        self.test_mode = test_mode
        self.playback_csv = playback_csv
        self.playback_type = playback_type

        self.test_config.update(self.test_config_widget.get_config())
        self.control_buttons.set_testing_mode(True)

        mode_label = "IBIT" if test_mode == TestMode.IBIT else f"Playback ({playback_type})"
        self.log("=" * 56)
        self.log(f"  BATCH START  --  {mode_label}  ({duration_seconds}s)")
        self.log("=" * 56)

        self._watchdog = BatchWatchdog(
            uuts=self.uuts,
            daq=self.daq,
            log_directory=self.log_directory,
            on_alert=lambda msg: self.show_alert(msg, severity=AlertSeverity.WARNING),
            on_log=self.log,
            is_testing=lambda: self.testing_active,
            current_uut_index=lambda: self.current_uut_index,
        )
        self._watchdog.start()

        self.elapsed_timer.start(1000)
        self.start_next_uut()

        if platform.system() == "Windows":
            try:
                import ctypes
                ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)
                self.log("✓ Windows sleep prevention active")
            except Exception:
                pass

    def closeEvent(self, event):
        # S-12: Force all relays OFF immediately before asking user
        if self.testing_active and self.daq:
            try:
                self.daq.set_all_low()
                self.log("\u26a0 Window closing \u2014 all relays forced OFF")
            except Exception:
                pass  # Best effort

        if self.testing_active:
            reply = QMessageBox.question(
                self, "Test Running",
                "A test is running. Stop and exit?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                event.ignore()
                return

        if self._watchdog:
            self._watchdog.stop()
        if self.current_test_executor:
            self.current_test_executor.stop()
        self.save_settings()
        if self.daq:
            try:
                self.daq.close()
            except Exception:
                pass
        event.accept()
