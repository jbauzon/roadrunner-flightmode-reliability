"""
ui.widgets.debug_console -- Manual MAVLink command console for debug/test use.

Allows the operator to manually send mode requests, ARM/DISARM, parameter
sets, and monitor overrides to any connected UUT without going through
the full automated test sequence.

Intended for:
  - Placing the vehicle in specific transition states for manual inspection
  - Testing individual MAVLink commands
  - Diagnosing connectivity or firmware issues

WARNING: Commands sent here bypass all safety checks.
         Only use when testing is NOT active.
"""
from __future__ import annotations

from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QGroupBox,
    QPushButton, QComboBox, QLabel, QLineEdit,
    QTextEdit, QSplitter, QDoubleSpinBox, QSpinBox,
    QGridLayout,
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont

from .. import theme as T
from .primitives import _label, _section_title


class DebugConsoleWidget(QWidget):
    """
    Manual MAVLink command console.
    
    Signals:
        command_sent(str): Emitted with a description whenever a command is sent
    """
    
    command_sent = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._master = None       # active mavlink connection
        self._master_lock = None  # threading.Lock
        self._uut_serial = None
        self._init_ui()
    
    # ── Public API ───────────────────────────────────────────────────────
    
    def set_connection(self, master, master_lock, uut_serial: str) -> None:
        """Set the active MAVLink connection for this console."""
        self._master = master
        self._master_lock = master_lock
        self._uut_serial = uut_serial
        self._update_enabled()
        self._log(f"Connected to {uut_serial}", 'info')
    
    def clear_connection(self) -> None:
        """Clear the active connection (e.g., after test completes)."""
        self._master = None
        self._master_lock = None
        self._uut_serial = None
        self._update_enabled()
        self._log("Connection cleared", 'warn')

    def set_test_active(self, active: bool) -> None:
        """Show/hide the test-active warning banner."""
        self._active_warning.setVisible(active)
    
    def _update_enabled(self) -> None:
        """Enable/disable command buttons based on connection state."""
        connected = self._master is not None
        for w in (self._mode_group, self._arm_group, self._param_group,
                  self._monitor_group, self._raw_group):
            w.setEnabled(connected)
        status = (
            f"Connected: {self._uut_serial}" if connected
            else "Not connected — start a test first"
        )
        self._status_label.setText(status)
        self._status_label.setStyleSheet(
            f"color: {T.GREEN if connected else T.AMBER}; "
            f"font-size: {T.FONT_SIZE_SM}; background: transparent;"
        )
    
    # ── UI construction ──────────────────────────────────────────────────
    
    def _init_ui(self) -> None:
        self.setStyleSheet(f"background: {T.BG_BASE};")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Title bar with amber background for visibility
        title_bar = QWidget()
        title_bar.setFixedHeight(36)
        title_bar.setStyleSheet(
            f"background: {T.BG_ELEVATED}; border-bottom: 1px solid {T.BORDER}; border-radius: 0;"
        )
        title_row = QHBoxLayout(title_bar)
        title_row.setContentsMargins(12, 0, 12, 0)
        title = QLabel("⚙  MANUAL COMMANDS")
        title.setStyleSheet(
            f"color: {T.AMBER}; font-size: {T.FONT_SIZE_SM}; font-weight: bold; "
            f"background: transparent; letter-spacing: 1px;"
        )
        self._status_label = QLabel("Not connected")
        self._status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._status_label.setStyleSheet(
            f"color: {T.TEXT_DISABLED}; font-size: {T.FONT_SIZE_SM}; background: transparent;"
        )
        title_row.addWidget(title)
        title_row.addStretch()
        title_row.addWidget(self._status_label)
        layout.addWidget(title_bar)

        # Warning: test is running
        self._active_warning = QLabel(
            "⚠  TEST IS RUNNING — commands will interrupt the sequence"
        )
        self._active_warning.setStyleSheet(
            f"background: #2e1a1a; color: {T.RED}; padding: 6px 12px; "
            f"font-size: {T.FONT_SIZE_SM}; font-weight: bold; "
            f"border-bottom: 1px solid {T.RED};"
        )
        self._active_warning.hide()
        layout.addWidget(self._active_warning)

        # Single scrollable column — all groups stacked vertically
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(12, 8, 12, 8)
        main_layout.setSpacing(8)
        layout.addLayout(main_layout)

        main_layout.addWidget(self._build_mode_group())
        main_layout.addWidget(self._build_arm_group())
        main_layout.addWidget(self._build_param_group())
        main_layout.addWidget(self._build_monitor_group())
        main_layout.addWidget(self._build_raw_group())
        main_layout.addWidget(self._build_log(), 1)
        main_layout.addStretch()

        self._update_enabled()
    
    def _build_mode_group(self) -> QGroupBox:
        self._mode_group = QGroupBox("Actuation Mode Request")
        self._mode_group.setStyleSheet(self._group_style())
        grid = QGridLayout(self._mode_group)
        grid.setSpacing(6)
        
        modes = [
            ("OFF",           0, T.TEXT_DISABLED),
            ("OPERATE",       2, T.GREEN),
            ("PLAYBACK",      4, T.BLUE),
            ("IBIT",          1, T.AMBER),
            ("MANUAL",        3, T.PURPLE),
            ("TRIM",          5, T.TEXT_SECONDARY),
            ("POS CHECK",     6, T.BLUE),
            ("TERMINAL",      7, T.RED),
        ]
        DIM_COLORS = {
            0: (T.TEXT_DISABLED, T.BG_ELEVATED),    # OFF — grey
            2: (T.GREEN,  '#1a2e1a'),                # OPERATE — green
            4: (T.BLUE,   '#1a1a2e'),                # PLAYBACK — blue
            1: (T.AMBER,  '#2e2a1a'),                # IBIT — amber
            3: (T.PURPLE, '#261a2e'),                # MANUAL — purple
            5: (T.TEXT_SECONDARY, T.BG_ELEVATED),   # TRIM — grey
            6: (T.BLUE,   '#1a1a2e'),                # POS CHECK — blue
            7: (T.RED,    '#2e1a1a'),                # TERMINAL — red
        }
        for i, (name, mode_id, color) in enumerate(modes):
            btn = QPushButton(name)
            btn.setFixedHeight(28)
            btn.setToolTip(f"Send pandion_rr_actuation_request_mode (requested_mode={mode_id})")
            color, bg = DIM_COLORS.get(mode_id, (T.TEXT_SECONDARY, T.BG_ELEVATED))
            btn.setStyleSheet(
                f"QPushButton {{ background: {bg}; color: {color}; "
                f"border: 1px solid {color}; border-radius: 4px; "
                f"padding: 4px 8px; font-size: {T.FONT_SIZE_SM}; font-weight: bold; }}"
                f"QPushButton:hover {{ background: {color}; color: {T.BG_BASE}; }}"
                f"QPushButton:disabled {{ background: {T.BG_BASE}; color: {T.TEXT_DISABLED}; "
                f"border-color: {T.BORDER}; }}"
            )
            btn.clicked.connect(lambda _, m=mode_id, n=name: self._send_mode_request(m, n))
            grid.addWidget(btn, i // 4, i % 4)
        
        return self._mode_group
    
    def _build_arm_group(self) -> QGroupBox:
        self._arm_group = QGroupBox("ARM / DISARM")
        self._arm_group.setStyleSheet(self._group_style())
        row = QHBoxLayout(self._arm_group)
        row.setSpacing(8)
        
        arm_btn = QPushButton("ARM")
        arm_btn.setFixedHeight(32)
        arm_btn.setToolTip("MAV_CMD_COMPONENT_ARM_DISARM param1=1")
        arm_btn.setStyleSheet(self._btn_style(T.GREEN))
        arm_btn.clicked.connect(lambda: self._send_arm(True))
        
        force_btn = QPushButton("Force ARM")
        force_btn.setFixedHeight(32)
        force_btn.setToolTip("MAV_CMD_COMPONENT_ARM_DISARM param1=1 param2=21196 (bypass monitors)")
        force_btn.setStyleSheet(self._btn_style(T.AMBER))
        force_btn.clicked.connect(lambda: self._send_arm(True, force=True))
        
        disarm_btn = QPushButton("DISARM")
        disarm_btn.setFixedHeight(32)
        disarm_btn.setToolTip("MAV_CMD_COMPONENT_ARM_DISARM param1=0")
        disarm_btn.setStyleSheet(self._btn_style(T.RED))
        disarm_btn.clicked.connect(lambda: self._send_arm(False))
        
        row.addWidget(arm_btn)
        row.addWidget(force_btn)
        row.addWidget(disarm_btn)
        return self._arm_group
    
    def _build_param_group(self) -> QGroupBox:
        self._param_group = QGroupBox("Parameter Set")
        self._param_group.setStyleSheet(self._group_style())
        grid = QGridLayout(self._param_group)
        grid.setSpacing(6)
        
        # Quick presets
        presets = [
            ("USE_NEST = 0",     "USE_NEST",        0),
            ("USE_NEST = 1",     "USE_NEST",        1),
            ("CLASSIC_MODE = 0", "CLASSIC_MODE_EN", 0),
            ("CLASSIC_MODE = 1", "CLASSIC_MODE_EN", 1),
        ]
        for i, (label, pname, val) in enumerate(presets):
            btn = QPushButton(label)
            btn.setFixedHeight(26)
            btn.setStyleSheet(self._btn_style(T.TEXT_SECONDARY, small=True))
            btn.clicked.connect(lambda _, n=pname, v=val: self._send_param(n, v))
            grid.addWidget(btn, i // 2, i % 2)
        
        # Custom param row
        grid.addWidget(QLabel("Custom:"), 2, 0)
        self._param_name = QLineEdit()
        self._param_name.setPlaceholderText("PARAM_NAME")
        self._param_name.setStyleSheet(self._input_style())
        self._param_name.setFixedHeight(26)
        grid.addWidget(self._param_name, 2, 1)
        
        self._param_val = QDoubleSpinBox()
        self._param_val.setRange(-1e6, 1e6)
        self._param_val.setDecimals(0)
        self._param_val.setStyleSheet(self._input_style())
        self._param_val.setFixedHeight(26)
        grid.addWidget(self._param_val, 3, 0)
        
        send_btn = QPushButton("Send")
        send_btn.setFixedHeight(26)
        send_btn.setStyleSheet(self._btn_style(T.BLUE, small=True))
        send_btn.clicked.connect(
            lambda: self._send_param(self._param_name.text(), int(self._param_val.value()))
        )
        grid.addWidget(send_btn, 3, 1)
        
        return self._param_group
    
    def _build_monitor_group(self) -> QGroupBox:
        self._monitor_group = QGroupBox("Monitor Override")
        self._monitor_group.setStyleSheet(self._group_style())
        grid = QGridLayout(self._monitor_group)
        grid.setSpacing(6)
        
        grid.addWidget(QLabel("Monitor ID:"), 0, 0)
        self._mon_id = QSpinBox()
        self._mon_id.setRange(0, 300)
        self._mon_id.setStyleSheet(self._input_style())
        self._mon_id.setFixedHeight(26)
        self._mon_id.setToolTip("Monitor ID from cm_config.xml (e.g., 9=Thermal Limit)")
        grid.addWidget(self._mon_id, 0, 1)
        
        suppress_btn = QPushButton("Suppress (1)")
        suppress_btn.setFixedHeight(26)
        suppress_btn.setToolTip(
            "MONITOR_OVERRIDE_SUPPRESS (cmd=1) — override to healthy\n"
            "Use to clear a SET monitor"
        )
        suppress_btn.setStyleSheet(self._btn_style(T.GREEN, small=True))
        suppress_btn.clicked.connect(
            lambda: self._send_monitor_override(1, self._mon_id.value())
        )
        
        cancel_btn = QPushButton("Cancel (0)")
        cancel_btn.setFixedHeight(26)
        cancel_btn.setToolTip(
            "MONITOR_OVERRIDE_CANCEL (cmd=0) — remove override, return to normal"
        )
        cancel_btn.setStyleSheet(self._btn_style(T.TEXT_SECONDARY, small=True))
        cancel_btn.clicked.connect(
            lambda: self._send_monitor_override(0, self._mon_id.value())
        )
        
        force_btn = QPushButton("Force Fault (2)")
        force_btn.setFixedHeight(26)
        force_btn.setToolTip(
            "MONITOR_OVERRIDE_FORCE_FAULT (cmd=2) — force monitor to faulted state"
        )
        force_btn.setStyleSheet(self._btn_style(T.RED, small=True))
        force_btn.clicked.connect(
            lambda: self._send_monitor_override(2, self._mon_id.value())
        )
        
        grid.addWidget(suppress_btn, 1, 0)
        grid.addWidget(cancel_btn,   1, 1)
        grid.addWidget(force_btn,    2, 0, 1, 2)
        
        # Known monitor quick buttons
        grid.addWidget(QLabel("Quick:"), 3, 0, 1, 2)
        known = [
            ("M6 Temp Warn",     6),
            ("M7 Temp Crit",     7),
            ("M9 Thermal Limit", 9),
            ("M52 Elevon Limit", 52),
            ("M55 IBIT Mismatch",55),
        ]
        for i, (lbl, mid) in enumerate(known):
            btn = QPushButton(lbl)
            btn.setFixedHeight(24)
            btn.setToolTip(f"Set monitor ID to {mid}")
            btn.setStyleSheet(self._btn_style(T.TEXT_DISABLED, small=True))
            btn.clicked.connect(lambda _, m=mid: self._mon_id.setValue(m))
            grid.addWidget(btn, 4 + i // 2, i % 2)
        
        return self._monitor_group
    
    def _build_raw_group(self) -> QGroupBox:
        self._raw_group = QGroupBox("Raw COMMAND_LONG")
        self._raw_group.setStyleSheet(self._group_style())
        grid = QGridLayout(self._raw_group)
        grid.setSpacing(4)
        
        self._cmd_id = QSpinBox()
        self._cmd_id.setRange(0, 65535)
        self._cmd_id.setValue(400)
        self._cmd_id.setStyleSheet(self._input_style())
        self._cmd_id.setFixedHeight(24)
        self._cmd_id.setToolTip("MAV_CMD ID (e.g., 400=ARM_DISARM)")
        
        self._cmd_p1 = QDoubleSpinBox()
        self._cmd_p1.setRange(-1e6, 1e6)
        self._cmd_p1.setStyleSheet(self._input_style())
        self._cmd_p1.setFixedHeight(24)
        
        grid.addWidget(QLabel("CMD:"), 0, 0)
        grid.addWidget(self._cmd_id, 0, 1)
        grid.addWidget(QLabel("p1:"), 0, 2)
        grid.addWidget(self._cmd_p1, 0, 3)
        
        send_btn = QPushButton("Send")
        send_btn.setFixedHeight(24)
        send_btn.setStyleSheet(self._btn_style(T.RED, small=True))
        send_btn.setToolTip("Send raw COMMAND_LONG — use with caution")
        send_btn.clicked.connect(
            lambda: self._send_raw_command(self._cmd_id.value(), self._cmd_p1.value())
        )
        grid.addWidget(send_btn, 1, 0, 1, 4)
        
        return self._raw_group
    
    def _build_log(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        
        header = QHBoxLayout()
        header.addWidget(_label("Response Log", T.TEXT_SECONDARY))
        clear_btn = QPushButton("Clear")
        clear_btn.setFixedHeight(20)
        clear_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {T.TEXT_DISABLED}; "
            f"border: 1px solid {T.BORDER}; border-radius: 3px; "
            f"padding: 1px 8px; font-size: {T.FONT_SIZE_SM}; }}"
        )
        clear_btn.clicked.connect(lambda: self._log_text.clear())
        header.addStretch()
        header.addWidget(clear_btn)
        layout.addLayout(header)
        
        self._log_text = QTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setMaximumHeight(120)
        self._log_text.setFont(QFont(T.FONT_MONO, int(T.FONT_SIZE_SM.replace('pt', ''))))
        self._log_text.setStyleSheet(
            f"QTextEdit {{ background: {T.BG_BASE}; color: {T.GREEN}; "
            f"border: 1px solid {T.BORDER}; border-radius: 4px; "
            f"font-family: {T.FONT_MONO}; }}"
        )
        layout.addWidget(self._log_text)
        return container
    
    # ── Command senders ──────────────────────────────────────────────────
    
    def _send_mode_request(self, mode_id: int, mode_name: str) -> None:
        if not self._ready(): return
        try:
            with self._master_lock:
                self._master.mav.pandion_rr_actuation_request_mode_send(
                    requested_mode=mode_id
                )
            msg = f"-> Mode request: {mode_name} ({mode_id})"
            self._log(msg, 'send')
            self.command_sent.emit(msg)
        except Exception as e:
            self._log(f"x Mode request failed: {e}", 'error')
    
    def _send_arm(self, arm: bool, force: bool = False) -> None:
        if not self._ready(): return
        try:
            from pymavlink import mavutil
            param2 = 21196 if force and arm else 0
            with self._master_lock:
                self._master.mav.command_long_send(
                    self._master.target_system, 1,
                    mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
                    0, float(arm), float(param2), 0, 0, 0, 0, 0,
                )
            label = ("Force ARM" if force else "ARM") if arm else "DISARM"
            msg = f"-> {label} command sent"
            self._log(msg, 'send')
            self.command_sent.emit(msg)
        except Exception as e:
            self._log(f"x ARM/DISARM failed: {e}", 'error')
    
    def _send_param(self, param_name: str, value: int) -> None:
        if not self._ready(): return
        if not param_name.strip():
            self._log("x Parameter name is empty", 'error')
            return
        try:
            from pymavlink import mavutil
            with self._master_lock:
                self._master.mav.param_set_send(
                    self._master.target_system, 1,
                    param_name.encode('utf-8'),
                    float(value),
                    mavutil.mavlink.MAV_PARAM_TYPE_UINT8,
                )
            msg = f"-> PARAM_SET {param_name} = {value}"
            self._log(msg, 'send')
            self.command_sent.emit(msg)
        except Exception as e:
            self._log(f"x Param set failed: {e}", 'error')
    
    def _send_monitor_override(self, cmd: int, monitor_id: int) -> None:
        if not self._ready(): return
        try:
            cmd_names = {0: 'CANCEL', 1: 'SUPPRESS', 2: 'FORCE_FAULT'}
            with self._master_lock:
                self._master.mav.pandion_monitor_override_cmd_send(
                    override_cmd=cmd,
                    monitor_id=monitor_id,
                )
            msg = f"-> Monitor {monitor_id}: {cmd_names.get(cmd, cmd)}"
            self._log(msg, 'send')
            self.command_sent.emit(msg)
        except Exception as e:
            self._log(f"x Monitor override failed: {e}", 'error')
    
    def _send_raw_command(self, cmd_id: int, param1: float) -> None:
        if not self._ready(): return
        try:
            with self._master_lock:
                self._master.mav.command_long_send(
                    self._master.target_system, 1,
                    int(cmd_id), 0, param1, 0, 0, 0, 0, 0, 0,
                )
            msg = f"-> COMMAND_LONG cmd={cmd_id} p1={param1}"
            self._log(msg, 'send')
            self.command_sent.emit(msg)
        except Exception as e:
            self._log(f"x Raw command failed: {e}", 'error')
    
    # ── Helpers ──────────────────────────────────────────────────────────
    
    def _ready(self) -> bool:
        if not self._master or not self._master_lock:
            self._log("x No active connection", 'error')
            return False
        return True
    
    def _log(self, message: str, level: str = 'info') -> None:
        colors = {
            'send':  T.GREEN,
            'info':  T.TEXT_SECONDARY,
            'warn':  T.AMBER,
            'error': T.RED,
        }
        color = colors.get(level, T.TEXT_SECONDARY)
        from datetime import datetime
        ts = datetime.now().strftime('%H:%M:%S')
        html = (
            f'<span style="color:{T.TEXT_DISABLED};">[{ts}] </span>'
            f'<span style="color:{color};">{message}</span>'
        )
        self._log_text.append(html)
        sb = self._log_text.verticalScrollBar()
        sb.setValue(sb.maximum())
    
    def _group_style(self) -> str:
        return (
            f"QGroupBox {{ color: {T.TEXT_SECONDARY}; "
            f"border: 1px solid {T.BORDER}; border-radius: 6px; "
            f"margin-top: 18px; padding: 8px; "
            f"font-size: {T.FONT_SIZE_SM}; font-weight: bold; }}"
            f"QGroupBox::title {{ subcontrol-origin: margin; left: 8px; "
            f"padding: 0 4px; }}"
            f"QGroupBox:disabled {{ opacity: 0.4; }}"
        )
    
    def _btn_style(self, color: str, small: bool = False) -> str:
        h = T.FONT_SIZE_SM if small else T.FONT_SIZE
        return (
            f"QPushButton {{ background: {T.BG_ELEVATED}; color: {color}; "
            f"border: 1px solid {T.BORDER}; border-radius: 4px; "
            f"padding: 2px 6px; font-size: {h}; }}"
            f"QPushButton:hover {{ border-color: {color}; background: {T.BG_SURFACE}; }}"
            f"QPushButton:disabled {{ color: {T.TEXT_DISABLED}; border-color: {T.BORDER}; }}"
        )
    
    def _input_style(self) -> str:
        return (
            f"background: {T.BG_BASE}; color: {T.TEXT_PRIMARY}; "
            f"border: 1px solid {T.BORDER}; border-radius: 3px; "
            f"padding: 2px 4px; font-family: {T.FONT_MONO}; "
            f"font-size: {T.FONT_SIZE_SM};"
        )
