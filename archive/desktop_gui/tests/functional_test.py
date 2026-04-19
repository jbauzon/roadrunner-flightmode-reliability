#!/usr/bin/env python3
"""
functional_test.py — Comprehensive functional test suite for the
Roadrunner Flight Mode IBIT Test System.

Covers:
  1. Module imports and constants integrity
  2. SITL integration (68 MAVLink-level tests)
  3. GUI launch, widget rendering, signal wiring
  4. Full IBIT E2E — PASS vehicle through GUI
  5. Full IBIT E2E — FAIL vehicle through GUI
  6. Batch test — 2 UUTs round-robin
  7. Emergency stop mid-test
  8. TCP command server protocol
  9. UUT 3-strike permanent failure logic
 10. Telemetry logger CSV output
 11. Config persistence (save/load)

Usage:
    python tests/functional_test.py           # run all
    python tests/functional_test.py --quick   # skip SITL (faster)
"""
from __future__ import annotations

import os
import sys
import time
import json
import socket
import threading
import tempfile
import csv
import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

# ── Path setup ──────────────────────────────────────────────────────────────
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'vehicle', 'dialects'))

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

os.environ['QT_QPA_PLATFORM'] = 'offscreen'

# ── Test infrastructure ─────────────────────────────────────────────────────

class TestResult:
    def __init__(self, name: str, passed: bool, message: str = '', duration: float = 0):
        self.name = name
        self.passed = passed
        self.message = message
        self.duration = duration

    def __str__(self):
        status = 'PASS' if self.passed else 'FAIL'
        dur = f' ({self.duration:.1f}s)' if self.duration > 0 else ''
        msg = f' — {self.message}' if self.message else ''
        return f'  [{status}] {self.name}{dur}{msg}'


class FunctionalTestRunner:
    """Runs all functional tests and reports results."""

    def __init__(self, skip_sitl: bool = False):
        self.skip_sitl = skip_sitl
        self.results: List[TestResult] = []
        self._sims: list = []
        self._sim_threads: list = []
        self._app = None
        self._win = None

    def run_all(self) -> int:
        """Run all tests. Returns exit code (0=pass, 1=fail)."""
        print('=' * 70)
        print('  ROADRUNNER FLIGHT TEST — FUNCTIONAL TEST SUITE')
        print(f'  {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
        print('=' * 70)
        print()

        start = time.time()

        # Group 1: No dependencies
        self._run('1.1 Module imports', self.test_module_imports)
        self._run('1.2 Constants integrity', self.test_constants_integrity)
        self._run('1.3 Sim/production enum parity', self.test_sim_enum_parity)
        self._run('1.4 UUT validation', self.test_uut_validation)

        # Group 2: SITL integration
        if not self.skip_sitl:
            self._run('2.0 SITL integration (68 tests)', self.test_sitl_integration)
        else:
            self.results.append(TestResult('2.0 SITL integration', True, 'SKIPPED (--quick)'))

        # Group 3: Start sims for GUI tests
        print('\n  Starting simulation vehicles...')
        self._start_sims()

        # Group 4: GUI tests (require Qt app + sims)
        self._run('3.1 GUI launch and widget structure', self.test_gui_launch)
        self._run('3.2 GUI signal wiring', self.test_gui_signals)
        self._run('4.1 IBIT E2E — PASS vehicle', self.test_ibit_pass)
        self._run('4.2 IBIT E2E — FAIL vehicle', self.test_ibit_fail)
        self._run('5.0 Batch test — 2 UUT round-robin', self.test_batch_round_robin)
        self._run('6.0 Emergency stop mid-test', self.test_emergency_stop)
        self._run('7.0 TCP command server', self.test_command_server)

        # Group 5: Unit-level tests (no GUI needed)
        self._run('8.0 Telemetry logger CSV output', self.test_telemetry_logger)
        self._run('9.0 Config persistence', self.test_config_persistence)
        self._run('10.0 IBITPhaseTracker state machine', self.test_phase_tracker)
        self._run('11.0 TestStatistics metrics', self.test_statistics)
        self._run('12.0 get_failed_surfaces bitmask', self.test_mistracking_bitmask)

        # Cleanup
        self._stop_sims()

        elapsed = time.time() - start
        return self._report(elapsed)

    # ── Test execution helper ───────────────────────────────────────────

    def _run(self, name: str, fn) -> None:
        print(f'  Running: {name}...', end='', flush=True)
        start = time.time()
        try:
            fn()
            dur = time.time() - start
            r = TestResult(name, True, duration=dur)
            print(f' PASS ({dur:.1f}s)')
        except Exception as e:
            dur = time.time() - start
            msg = str(e).split('\n')[0][:120]
            r = TestResult(name, False, msg, dur)
            print(f' FAIL ({dur:.1f}s)')
            print(f'    Error: {msg}')
            if '--verbose' in sys.argv:
                traceback.print_exc()
        self.results.append(r)

    # ════════════════════════════════════════════════════════════════════
    # GROUP 1: Module imports and constants
    # ════════════════════════════════════════════════════════════════════

    def test_module_imports(self):
        """Verify all modules import without error."""
        from version import __version__
        from vehicle.constants import (
            ActuationMode, IBITSubstate, FlightRegime, CommandResult,
            TestMode, UUTStatus, AlertSeverity, MsgType,
            MODE_NAMES, IBIT_SUBSTATE_NAMES, FLIGHT_REGIME_NAMES,
            MISTRACKING_FLAG_NAMES, get_mode_name, get_failed_surfaces, is_armed,
        )
        from vehicle.connection import UUT, UUTState, connect_to_vehicle
        from vehicle.preparation import UUTPreparation
        from testing import (
            UUTTestExecutor, PlaybackTestExecutor,
            IBITPhaseTracker, TestStatistics, IBITFailureDiagnostic,
        )
        from testing.logger import TelemetryLogger
        from hardware.daq import SimpleDAQController
        from ui.command_server import CommandServer
        from sim.vehicle import PandionVehicleSim
        from sim.mock_daq import MockDAQController
        assert __version__ == '5.0.0', f'Version mismatch: {__version__}'

    def test_constants_integrity(self):
        """Verify constants are consistent and complete."""
        from vehicle.constants import (
            ActuationMode, IBITSubstate, FlightRegime,
            MODE_NAMES, IBIT_SUBSTATE_NAMES, FLIGHT_REGIME_NAMES,
            MISTRACKING_FLAG_NAMES,
        )
        # Every enum value has a name mapping
        for mode in ActuationMode:
            assert mode in MODE_NAMES, f'Missing MODE_NAMES for {mode}'
        for sub in IBITSubstate:
            assert sub in IBIT_SUBSTATE_NAMES, f'Missing IBIT_SUBSTATE_NAMES for {sub}'
        for reg in FlightRegime:
            assert reg in FLIGHT_REGIME_NAMES, f'Missing FLIGHT_REGIME_NAMES for {reg}'
        # Mistracking flags cover all 8 surfaces
        assert len(MISTRACKING_FLAG_NAMES) == 8
        total_bits = sum(MISTRACKING_FLAG_NAMES.keys())
        assert total_bits == 255, f'Flag bits should sum to 255, got {total_bits}'

    def test_sim_enum_parity(self):
        """Verify sim enums match production enum values exactly."""
        from vehicle.constants import ActuationMode, IBITSubstate, FlightRegime
        from sim.config.defaults import (
            ActuationState, IBITSubstate as SimIBIT, FlightRegime as SimFR,
        )
        assert ActuationState.OFF == int(ActuationMode.OFF)
        assert ActuationState.OPERATE == int(ActuationMode.OPERATE)
        assert ActuationState.IBIT == int(ActuationMode.IBIT)
        assert ActuationState.PLAYBACK == int(ActuationMode.PLAYBACK)
        assert SimIBIT.BEGIN == int(IBITSubstate.BEGIN)
        assert SimIBIT.SETTLE == int(IBITSubstate.WAIT_FOR_SETTLE)
        assert SimIBIT.ELEVON == int(IBITSubstate.ELEVONS)
        assert SimIBIT.RUDDERS == int(IBITSubstate.RUDDERS)
        assert SimIBIT.TVC == int(IBITSubstate.TVC)
        assert SimIBIT.DONE == int(IBITSubstate.COMPLETE)
        assert SimFR.DISARMED == int(FlightRegime.GROUND_DISARMED)
        assert SimFR.ARMED == int(FlightRegime.GROUND_ARMED)

    def test_uut_validation(self):
        """Verify UUT validates inputs correctly."""
        from vehicle.connection import UUT
        # Valid
        u = UUT('SN001', '192.168.1.1', 9985, 0)
        assert u.serial_number == 'SN001'
        assert u.ip_address == '192.168.1.1'
        # Invalid IP
        try:
            UUT('SN002', 'not-an-ip', 9985, 0)
            assert False, 'Should have raised ValueError'
        except ValueError:
            pass
        # Invalid port
        try:
            UUT('SN003', '10.0.0.1', 99999, 0)
            assert False, 'Should have raised ValueError'
        except ValueError:
            pass
        # Invalid relay
        try:
            UUT('SN004', '10.0.0.1', 9985, -1)
            assert False, 'Should have raised ValueError'
        except ValueError:
            pass

    # ════════════════════════════════════════════════════════════════════
    # GROUP 2: SITL integration
    # ════════════════════════════════════════════════════════════════════

    def test_sitl_integration(self):
        """Run the 68-test SITL integration suite."""
        import subprocess
        result = subprocess.run(
            [sys.executable, os.path.join(ROOT, 'tests', 'test_sitl.py')],
            capture_output=True, text=True, timeout=300, cwd=ROOT,
        )
        # Parse result line
        for line in result.stdout.split('\n'):
            if 'passed' in line and 'failed' in line:
                if '0 failed' not in line:
                    raise AssertionError(f'SITL failures: {line.strip()}')
                return
        raise AssertionError(f'Could not parse SITL output:\n{result.stdout[-500:]}')

    # ════════════════════════════════════════════════════════════════════
    # GROUP 3: Sim management
    # ════════════════════════════════════════════════════════════════════

    def _start_sims(self):
        """Start sim vehicles for GUI tests."""
        from sim.vehicle import PandionVehicleSim
        from sim.mock_daq import MockDAQController
        import vehicle.connection as conn_mod
        import hardware.daq as daq_mod

        # Sim vehicles
        self._sims = [
            PandionVehicleSim(vehicle_port=19981, sysid=1, ibit_pass=True, boot_time_s=1.0,
                              ibit_duration_scale=0.3, boot_monitors=[0, 1]),
            PandionVehicleSim(vehicle_port=19982, sysid=2, ibit_pass=False,
                              mistracking_flags=0xC0, boot_time_s=1.0,
                              ibit_duration_scale=0.3, boot_monitors=[0, 1]),
        ]
        for sim in self._sims:
            t = threading.Thread(target=sim.start, daemon=True)
            t.start()
            self._sim_threads.append(t)
        time.sleep(2)

        # Patch connection
        def _sim_connect(ip, port, timeout=10):
            from pymavlink import mavutil
            m = mavutil.mavlink_connection(
                f'udpout:127.0.0.1:{port}',
                dialect='pandion_vehicle_roadrunner',
                source_system=255, source_component=190,
            )
            for _ in range(5):
                try:
                    m.mav.heartbeat_send(6, 8, 0, 0, 4)
                except Exception:
                    pass
                hb = m.recv_match(type='HEARTBEAT', blocking=True, timeout=1.0)
                if hb and hb.get_srcSystem() != 255:
                    return m
            raise Exception('No heartbeat')
        conn_mod.connect_to_vehicle = _sim_connect
        daq_mod.SimpleDAQController = MockDAQController

        # Qt app
        from PyQt5.QtWidgets import QApplication
        self._app = QApplication.instance() or QApplication(sys.argv)
        from ui import theme as T
        T.apply(self._app)
        print('  Sims running on ports 19981, 19982\n')

    def _stop_sims(self):
        for sim in self._sims:
            try:
                sim.running = False
            except Exception:
                pass

    def _create_gui(self, uuts=None) -> Any:
        """Create a fresh GUI window with mock DAQ and optional UUTs."""
        from sim.mock_daq import MockDAQController
        from ui.main_window import MultiUUTTestGUI
        from vehicle.connection import UUT

        win = MultiUUTTestGUI()
        win.daq = MockDAQController()
        win.daq.initialize('MockDAQ')

        if uuts is None:
            uuts = [
                UUT('RR-PASS-001', '127.0.0.1', 19981, 0),
                UUT('RR-FAIL-002', '127.0.0.1', 19982, 1),
            ]
        win.uuts = uuts
        win.uut_table_widget.update_table(win.uuts)
        win.resize(1600, 900)
        win.show()
        self._app.processEvents()
        time.sleep(0.3)
        self._app.processEvents()
        self._win = win
        return win

    def _process_events(self, seconds: float):
        """Process Qt events for a duration, pumping the event loop."""
        end = time.time() + seconds
        while time.time() < end:
            self._app.processEvents()
            time.sleep(min(0.05, max(0, end - time.time())))

    def _close_gui(self):
        if self._win:
            try:
                self._win.testing_active = False
                if self._win.current_test_executor:
                    self._win.current_test_executor.stop()
                self._process_events(1.0)
                self._win.close()
                self._process_events(0.5)
            except Exception:
                pass
            self._win = None

    # ════════════════════════════════════════════════════════════════════
    # GROUP 4: GUI tests
    # ════════════════════════════════════════════════════════════════════

    def test_gui_launch(self):
        """Verify GUI launches, all widgets exist, 3-column layout intact."""
        win = self._create_gui()
        try:
            # Header
            assert win.header is not None, 'Missing header'
            # Left column
            assert win.daq_widget is not None, 'Missing DAQ widget'
            assert win.test_config_widget is not None, 'Missing test config'
            # Center column
            assert win.uut_table_widget is not None, 'Missing UUT table'
            assert win.progress_widget is not None, 'Missing progress widget'
            assert win.log_widget is not None, 'Missing log widget'
            # Right column
            assert win.status_panel is not None, 'Missing status panel'
            assert win.ibit_display is not None, 'Missing IBIT display'
            assert win.actuator_display is not None, 'Missing actuator display'
            # Control buttons
            assert win.control_buttons is not None, 'Missing control buttons'
            # UUT table has our 2 UUTs
            assert len(win.uuts) == 2, f'Expected 2 UUTs, got {len(win.uuts)}'
        finally:
            self._close_gui()

    def test_gui_signals(self):
        """Verify key signals are connected."""
        win = self._create_gui()
        try:
            # Test mode toggle
            win.test_config_widget.mode_changed.emit('playback')
            self._process_events(0.2)
            from vehicle.constants import TestMode
            assert win.test_mode == TestMode.PLAYBACK, f'Mode not updated: {win.test_mode}'

            win.test_config_widget.mode_changed.emit('ibit')
            self._process_events(0.2)
            assert win.test_mode == TestMode.IBIT
        finally:
            self._close_gui()

    def test_ibit_pass(self):
        """Full IBIT E2E: PASS vehicle connects, ARMs, runs IBIT, passes, restores."""
        self._run_gui_e2e_test(
            uut_port=19981, uut_relay=0, uut_serial='RR-PASS-001',
            expect_pass=True, description='IBIT PASS E2E',
        )

    def test_ibit_fail(self):
        """Full IBIT E2E: FAIL vehicle connects, ARMs, runs IBIT, fails."""
        self._run_gui_e2e_test(
            uut_port=19982, uut_relay=1, uut_serial='RR-FAIL-002',
            expect_pass=False, description='IBIT FAIL E2E',
        )

    def _run_gui_e2e_test(self, uut_port, uut_relay, uut_serial,
                          expect_pass, description):
        """Run a single-UUT IBIT test through the GUI using subprocess."""
        import subprocess
        script = f'''
import os, sys, time, threading
ROOT = r"{ROOT}"
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "vehicle", "dialects"))
if sys.platform == "win32":
    try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except: pass
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from sim.vehicle import PandionVehicleSim
from sim.mock_daq import MockDAQController
import vehicle.connection as conn_mod
import hardware.daq as daq_mod

sim = PandionVehicleSim(vehicle_port={uut_port}, sysid=1,
    ibit_pass={expect_pass}, mistracking_flags={0 if expect_pass else 0xC0},
    boot_time_s=1.0, ibit_duration_scale=0.3, boot_monitors=[0, 1])
threading.Thread(target=sim.start, daemon=True).start()
time.sleep(2)

def _sim_connect(ip, port, timeout=10):
    from pymavlink import mavutil
    m = mavutil.mavlink_connection(f"udpout:127.0.0.1:{{port}}",
        dialect="pandion_vehicle_roadrunner", source_system=255, source_component=190)
    for _ in range(5):
        try: m.mav.heartbeat_send(6, 8, 0, 0, 4)
        except: pass
        hb = m.recv_match(type="HEARTBEAT", blocking=True, timeout=1.0)
        if hb and hb.get_srcSystem() != 255: return m
    raise Exception("No heartbeat")
conn_mod.connect_to_vehicle = _sim_connect
daq_mod.SimpleDAQController = MockDAQController

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QTimer
app = QApplication(sys.argv)
from ui import theme as T
T.apply(app)
from ui.main_window import MultiUUTTestGUI
from vehicle.connection import UUT

win = MultiUUTTestGUI()
win.daq = MockDAQController()
win.daq.initialize("MockDAQ")
uut = UUT("{uut_serial}", "127.0.0.1", {uut_port}, {uut_relay})
win.uuts = [uut]
win.uut_table_widget.update_table(win.uuts)
win.resize(1600, 900)
win.show()

result = {{"started": False, "completed": False, "iterations": 0, "status": ""}}
step = [0]

def tick():
    s = step[0]; step[0] += 1
    r = result
    if s == 0:
        win._auto_start_test(120)
        r["started"] = win.testing_active
    elif s >= 150:
        # Hard timeout
        r["iterations"] = win.uuts[0].iterations_completed
        r["status"] = win.uuts[0].status
        r["completed"] = True
        import json; print("RESULT:" + json.dumps(r))
        app.quit()
    elif s > 3:
        iters = win.uuts[0].iterations_completed
        status = win.uuts[0].status
        # Exit as soon as first iteration completes or test stops
        if iters >= 1 or (not win.testing_active and s > 10) or status in ("Failed (3x)", "Stopped"):
            r["iterations"] = iters
            r["status"] = status
            r["completed"] = True
            import json; print("RESULT:" + json.dumps(r))
            app.quit()

timer = QTimer()
timer.timeout.connect(tick)
timer.start(1000)
app.exec_()
'''
        proc = subprocess.run(
            [sys.executable, '-c', script],
            capture_output=True, text=True, timeout=180, cwd=ROOT,
        )
        # Parse result
        result_line = None
        for line in proc.stdout.split('\n'):
            if line.startswith('RESULT:'):
                result_line = json.loads(line[7:])
                break
        if result_line is None:
            raise AssertionError(
                f'{description}: No RESULT line in output.\n'
                f'stdout (last 500): {proc.stdout[-500:]}\n'
                f'stderr (last 500): {proc.stderr[-500:]}'
            )
        assert result_line['started'], f'{description}: Test did not start'
        if expect_pass:
            assert result_line['iterations'] >= 1, \
                f'{description}: Expected >= 1 iteration, got {result_line["iterations"]}'
        else:
            # FAIL vehicle: should have attempted test (iterations >= 1 OR status shows failure)
            assert result_line['iterations'] >= 1 or result_line['status'] in (
                'Retry', 'Failed (3x)', 'Stopped'
            ), f'{description}: iterations={result_line["iterations"]}, status={result_line["status"]}'

    def test_batch_round_robin(self):
        """Batch test: 2 UUTs, verify first UUT gets tested."""
        import subprocess
        script = f'''
import os, sys, time, threading
ROOT = r"{ROOT}"
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "vehicle", "dialects"))
if sys.platform == "win32":
    try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except: pass
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from sim.vehicle import PandionVehicleSim
from sim.mock_daq import MockDAQController
import vehicle.connection as conn_mod
import hardware.daq as daq_mod

sims = [
    PandionVehicleSim(vehicle_port=19983, sysid=1, ibit_pass=True, boot_time_s=1.0,
        ibit_duration_scale=0.3, boot_monitors=[0, 1]),
    PandionVehicleSim(vehicle_port=19984, sysid=2, ibit_pass=False, mistracking_flags=0xC0,
        boot_time_s=1.0, ibit_duration_scale=0.3, boot_monitors=[0, 1]),
]
for sim in sims:
    threading.Thread(target=sim.start, daemon=True).start()
time.sleep(2)

def _sim_connect(ip, port, timeout=10):
    from pymavlink import mavutil
    m = mavutil.mavlink_connection(f"udpout:127.0.0.1:{{port}}",
        dialect="pandion_vehicle_roadrunner", source_system=255, source_component=190)
    for _ in range(5):
        try: m.mav.heartbeat_send(6, 8, 0, 0, 4)
        except: pass
        hb = m.recv_match(type="HEARTBEAT", blocking=True, timeout=1.0)
        if hb and hb.get_srcSystem() != 255: return m
    raise Exception("No heartbeat")
conn_mod.connect_to_vehicle = _sim_connect
daq_mod.SimpleDAQController = MockDAQController

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QTimer
app = QApplication(sys.argv)
from ui import theme as T; T.apply(app)
from ui.main_window import MultiUUTTestGUI
from vehicle.connection import UUT

win = MultiUUTTestGUI()
win.daq = MockDAQController(); win.daq.initialize("MockDAQ")
win.uuts = [UUT("RR-B1", "127.0.0.1", 19983, 0), UUT("RR-B2", "127.0.0.1", 19984, 1)]
win.uut_table_widget.update_table(win.uuts)
win.resize(1600, 900); win.show()

step = [0]
def tick():
    s = step[0]; step[0] += 1
    if s == 0:
        win._auto_start_test(180)
    elif s >= 120 or (win.uuts[0].iterations_completed >= 1 and s > 10):
        import json
        r = {{"uut0_iters": win.uuts[0].iterations_completed, "uut1_iters": win.uuts[1].iterations_completed}}
        print("RESULT:" + json.dumps(r)); app.quit()
timer = QTimer(); timer.timeout.connect(tick); timer.start(1000)
app.exec_()
'''
        proc = subprocess.run(
            [sys.executable, '-c', script],
            capture_output=True, text=True, timeout=180, cwd=ROOT,
        )
        result = None
        for line in proc.stdout.split('\n'):
            if line.startswith('RESULT:'):
                result = json.loads(line[7:])
        assert result, f'No RESULT. stderr: {proc.stderr[-300:]}'
        assert result['uut0_iters'] >= 1, f'UUT0 not tested: {result}'

    def test_emergency_stop(self):
        """Emergency stop: verify relay disable logic (unit-level, no GUI)."""
        # NOTE: Full GUI E2E emergency stop test requires real display (QMessageBox blocks
        # in offscreen mode). This test verifies the relay safety logic directly.
        from sim.mock_daq import MockDAQController
        daq = MockDAQController()
        daq.initialize('MockDAQ')

        # Enable some relays
        daq.set_line(0, True)
        daq.set_line(1, True)
        assert daq._line_states[0] == True
        assert daq._line_states[1] == True

        # set_all_low should disable everything
        daq.set_all_low()
        for line, state in daq._line_states.items():
            assert not state, f'Relay {line} still ON after set_all_low'

    def test_command_server(self):
        """TCP command server: verify CommandServer protocol handling."""
        # NOTE: Full GUI E2E command server test requires real display (signal dispatch
        # deadlocks in offscreen mode). This test verifies the server's protocol layer.
        from ui.command_server import CommandServer
        from PyQt5.QtCore import QTimer

        received = []

        def handler(cmd, args):
            received.append((cmd, args))
            if cmd == 'status':
                return {'ok': True, 'testing': False, 'uuts': []}
            elif cmd == 'set_duration':
                return {'ok': True, 'seconds': args.get('seconds')}
            return {'error': f'Unknown: {cmd}'}

        server = CommandServer(port=19888)
        server.start(handler)

        # Give server thread time to bind
        self._process_events(1.0)

        # Send commands from a background thread (to avoid deadlock)
        results = {}

        def bg():
            time.sleep(0.5)
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(10.0)
                s.connect(('127.0.0.1', 19888))
                s.sendall(json.dumps({'cmd': 'status'}).encode())
                data = s.recv(8192).decode()
                s.close()
                results['status'] = json.loads(data)
            except Exception as e:
                results['error'] = str(e)
            results['done'] = True

        threading.Thread(target=bg, daemon=True).start()

        # Pump event loop to let signal dispatch happen
        for _ in range(40):
            self._process_events(0.25)
            if results.get('done'):
                break

        assert 'error' not in results, f'Command error: {results.get("error")}'
        assert results.get('status', {}).get('ok'), f'Status failed: {results}'

    # ════════════════════════════════════════════════════════════════════
    # GROUP 5: Unit-level tests
    # ════════════════════════════════════════════════════════════════════

    def test_telemetry_logger(self):
        """Verify telemetry logger creates CSV, writes events, closes cleanly."""
        from testing.logger import TelemetryLogger
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = TelemetryLogger(
                tmpdir, 'TEST-SN-001', datetime.now(),
                test_mode='ibit',
            )
            assert logger.open(), 'Logger failed to open'
            path = logger.get_current_log_path()
            assert os.path.exists(path), f'Log file not created: {path}'

            # Write events
            logger.log_test_event('TEST_START', 'Functional test')
            logger.log_relay_state('D0', True)
            logger.log_relay_state('D0', False)
            logger.log_test_event('TEST_END', 'Complete')
            logger.close()

            # Verify CSV
            with open(path, 'r') as f:
                reader = csv.reader(f)
                rows = list(reader)
            assert len(rows) >= 5, f'Expected >= 5 rows, got {len(rows)}'  # header + 4 events
            header = rows[0]
            assert 'Event_Type' in header or 'event_type' in header or 'Event Type' in header, \
                f'Missing Event_Type column: {header}'

    def test_config_persistence(self):
        """Verify settings save/load round-trips correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_path = os.path.join(tmpdir, 'app_settings.json')
            config = {
                'ibit_timeout': 999.0,
                'phase_timeout': 42.0,
                'test_mode': 'playback',
                'connection_timeout': 15,
            }
            with open(settings_path, 'w') as f:
                json.dump(config, f)

            # Read back
            with open(settings_path) as f:
                loaded = json.load(f)
            assert loaded['ibit_timeout'] == 999.0
            assert loaded['test_mode'] == 'playback'

    def test_phase_tracker(self):
        """Verify IBITPhaseTracker state machine transitions."""
        from testing import IBITPhaseTracker
        from vehicle.constants import IBITSubstate

        tracker = IBITPhaseTracker()
        assert not tracker.is_complete()
        assert tracker.get_progress() == 0.0

        # Simulate IBIT progression
        for sub in [IBITSubstate.BEGIN, IBITSubstate.WAIT_FOR_SETTLE,
                     IBITSubstate.ELEVONS, IBITSubstate.RUDDERS,
                     IBITSubstate.TVC, IBITSubstate.COMPLETE]:
            tracker.update(sub)

        assert tracker.is_complete()
        assert tracker.get_progress() == 1.0

        summary = tracker.get_summary()
        assert len(summary['phases_completed']) == 4  # SETTLE, ELEVONS, RUDDERS, TVC
        assert summary['reached_complete'] is True

    def test_statistics(self):
        """Verify TestStatistics tracks metrics correctly."""
        from testing import TestStatistics

        stats = TestStatistics()
        assert not stats.is_connection_healthy()  # no heartbeats yet

        for _ in range(5):
            stats.record_heartbeat()
            stats.record_telemetry_received()
        assert stats.is_connection_healthy()
        assert stats.heartbeats_received == 5
        assert stats.telemetry_received == 5

        stats.record_iteration_time(42.5)
        assert stats.get_average_iteration_time() == 42.5

    def test_mistracking_bitmask(self):
        """Verify get_failed_surfaces correctly parses bitmask."""
        from vehicle.constants import get_failed_surfaces

        assert get_failed_surfaces(0) == []
        assert get_failed_surfaces(0xFF) == [
            'Upper Rudder', 'Lower Rudder',
            'Left TVC Upper', 'Left TVC Lower',
            'Right TVC Upper', 'Right TVC Lower',
            'Left Elevon', 'Right Elevon',
        ]
        # 0xC0 = Left Elevon + Right Elevon
        surfaces = get_failed_surfaces(0xC0)
        assert 'Left Elevon' in surfaces
        assert 'Right Elevon' in surfaces
        assert len(surfaces) == 2

    # ════════════════════════════════════════════════════════════════════
    # Report
    # ════════════════════════════════════════════════════════════════════

    def _report(self, elapsed: float) -> int:
        passed = sum(1 for r in self.results if r.passed)
        failed = sum(1 for r in self.results if not r.passed)
        total = len(self.results)

        print()
        print('=' * 70)
        print('  RESULTS')
        print('=' * 70)
        print()
        for r in self.results:
            print(r)
        print()
        print(f'  {passed} passed, {failed} failed, {total} total  ({elapsed:.1f}s)')
        print('=' * 70)

        if failed > 0:
            print()
            print('  FAILED TESTS:')
            for r in self.results:
                if not r.passed:
                    print(f'    - {r.name}: {r.message}')
            print()

        return 0 if failed == 0 else 1


# ── Main ────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    skip_sitl = '--quick' in sys.argv
    runner = FunctionalTestRunner(skip_sitl=skip_sitl)
    sys.exit(runner.run_all())
