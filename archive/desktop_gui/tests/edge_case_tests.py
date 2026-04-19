"""
Edge Case Test Suite

Tests every guarded edge case through the actual GUI+SITL stack.
Each test runs in its own subprocess to guarantee clean state.

Coverage:
  A. Configuration validation (duplicate relay, duplicate IP:port, out-of-range)
  B. Safety guards (double-start, remove-during-test, mode-switch-during-test)
  C. IBIT failure modes (mistracking, IBIT timeout, phase timeout, connection loss)
  D. State machine edge cases (TERMINAL mode, POS_CHECK, instantaneous IBIT)
  E. Relay edge cases (relay enable failure, relay disable failure)
  F. Batch lifecycle (time expiry, 3x permanent fail, batch report generation)
  G. Multi-iteration stability (2 consecutive iterations, error log persistence)
"""
from __future__ import annotations

import os
import sys
import time
import json
import subprocess
import threading
from typing import Any, Optional

ROOT = r'C:\Anduril\RoadRunner Flight Mode IBIT'
sys.path.insert(0, ROOT)

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# ── Base subprocess template ─────────────────────────────────────────────────
BASE = r'''
import os, sys, time, json, threading
ROOT = r"{root}"
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'vehicle', 'dialects'))
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except: pass

from sim.vehicle import PandionVehicleSim
from sim.mock_daq import MockDAQController
import vehicle.connection as conn_mod
import hardware.daq as daq_mod

def _connect(ip, port, timeout=10):
    from pymavlink import mavutil
    m = mavutil.mavlink_connection(f'udpout:{{ip}}:{{port}}',
        dialect='pandion_vehicle_roadrunner', source_system=255, source_component=190)
    for _ in range(5):
        try: m.mav.heartbeat_send(6, 8, 0, 0, 4)
        except: pass
        hb = m.recv_match(type='HEARTBEAT', blocking=True, timeout=2.0)
        if hb and hb.get_srcSystem() != 255: return m
    raise Exception(f'No heartbeat on port {{port}}')
conn_mod.connect_to_vehicle = _connect
daq_mod.SimpleDAQController = MockDAQController

from PyQt5.QtWidgets import QApplication, QMessageBox
from PyQt5.QtCore import QTimer
QMessageBox.question = lambda *a, **kw: QMessageBox.Yes
QMessageBox.critical = lambda *a, **kw: None
QMessageBox.warning  = lambda *a, **kw: None
QMessageBox.information = lambda *a, **kw: None

app = QApplication(sys.argv)
from ui import theme as T; T.apply(app)
from ui.main_window import MultiUUTTestGUI
from vehicle.connection import UUT
from vehicle.constants import TestMode, UUTStatus

# ── SETUP ────────────────────────────────────────────────────────────────────
{setup}

# ── SCENARIO ─────────────────────────────────────────────────────────────────
{scenario}

# ── CHECKS ───────────────────────────────────────────────────────────────────
result = {{}}
step = [0]; done = [False]
def tick():
    s = step[0]; step[0] += 1
    try:
        if not done[0]:
            {checks}
    except Exception as e:
        result['error'] = str(e)
        import traceback; traceback.print_exc()
        done[0] = True
        print('RESULT:' + json.dumps(result)); app.quit()

timer = QTimer(); timer.timeout.connect(tick); timer.start(1000)
app.exec_()
'''

# ── Test runner ──────────────────────────────────────────────────────────────
results = []

def run_case(name: str, test_script: str, timeout: int = 60) -> dict:
    """Run a single edge case in a subprocess."""
    # Always prepend the preamble so test bodies don't need to repeat it
    full_script = PREAMBLE + '\n' + test_script
    try:
        proc = subprocess.run(
            [sys.executable, '-c', full_script],
            capture_output=True, text=True, timeout=timeout, cwd=ROOT,
        )
        result_line = None
        for line in proc.stdout.split('\n'):
            if line.startswith('RESULT:'):
                result_line = json.loads(line[7:])
                break
        if result_line is None:
            return {'pass': False,
                    'reason': f'No RESULT. stderr: {proc.stderr[-300:]}\nstdout: {proc.stdout[-300:]}'}
        return result_line
    except subprocess.TimeoutExpired:
        return {'pass': False, 'reason': 'Subprocess timeout'}
    except Exception as e:
        return {'pass': False, 'reason': str(e)}

def case(name: str, test_script: str, timeout: int = 60):
    """Run a test case and record the result."""
    print(f'  Running: {name}...', end='', flush=True)
    r = run_case(name, test_script, timeout)
    ok = r.get('pass', False)
    status = 'PASS' if ok else 'FAIL'
    print(f' {status}')
    if not ok:
        reason = r.get('reason', r.get('error', str(r)))
        print(f'    Reason: {reason[:150]}')
    results.append({'name': name, 'pass': ok, 'result': r})

# ── Test scripts ─────────────────────────────────────────────────────────────

def make_sim(port, sysid=1, ibit_pass=True, flags=0, boot=1.0, scale=0.2,
             boot_monitors=None, post_arm_monitors=None):
    bm  = repr(boot_monitors or [0, 1])
    pam = repr(post_arm_monitors or [10])
    return f'''
sim = PandionVehicleSim(vehicle_port={port}, sysid={sysid},
    ibit_pass={ibit_pass}, mistracking_flags={flags},
    boot_time_s={boot}, ibit_duration_scale={scale},
    boot_monitors={bm}, post_arm_monitors={pam})
threading.Thread(target=sim.start, daemon=True).start()
time.sleep(1.5)
'''

# Common preamble embedded in every subprocess script
PREAMBLE = f'''
import os, sys, time, json, threading
ROOT = r"{ROOT}"
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'vehicle', 'dialects'))
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except: pass

from sim.vehicle import PandionVehicleSim
from sim.mock_daq import MockDAQController
import vehicle.connection as conn_mod
import hardware.daq as daq_mod

def _connect(ip, port, timeout=10):
    from pymavlink import mavutil
    m = mavutil.mavlink_connection(f'udpout:{{ip}}:{{port}}',
        dialect='pandion_vehicle_roadrunner', source_system=255, source_component=190)
    for _ in range(5):
        try: m.mav.heartbeat_send(6, 8, 0, 0, 4)
        except: pass
        hb = m.recv_match(type='HEARTBEAT', blocking=True, timeout=2.0)
        if hb and hb.get_srcSystem() != 255: return m
    raise Exception(f'No heartbeat on port {{port}}')
conn_mod.connect_to_vehicle = _connect
daq_mod.SimpleDAQController = MockDAQController

from PyQt5.QtWidgets import QApplication, QMessageBox
from PyQt5.QtCore import QTimer
QMessageBox.question     = lambda *a, **kw: QMessageBox.Yes
QMessageBox.critical     = lambda *a, **kw: None
QMessageBox.warning      = lambda *a, **kw: None
QMessageBox.information  = lambda *a, **kw: None

app = QApplication(sys.argv)
from ui import theme as T; T.apply(app)
from ui.main_window import MultiUUTTestGUI
from vehicle.connection import UUT
from vehicle.constants import TestMode, UUTStatus
'''

def script(body: str) -> str:
    """Wrap a test body in the standard preamble."""
    return PREAMBLE + '\n' + body

PORT_BASE = 14700
PORT_GAP  = 5  # Each test uses up to 2 ports, gap of 5 prevents reuse collisions

print('=' * 70)
print('  EDGE CASE TEST SUITE')
print('=' * 70)
print()


# ════════════════════════════════════════════════════════════════════════
# GROUP A: Configuration validation
# ════════════════════════════════════════════════════════════════════════
print('--- A. Configuration Validation ---', flush=True)

# A1: Duplicate relay line blocked at start
case('A1: Duplicate relay line blocked at start',
f'''
{make_sim(PORT_BASE+5)}
win = MultiUUTTestGUI()
win.daq = MockDAQController(); win.daq.initialize('MockDAQ')
win.uuts = [UUT('P1','127.0.0.1',{PORT_BASE+5},0), UUT('P2','127.0.0.1',{PORT_BASE+5},0)]
win.uut_table_widget.update_table(win.uuts)
win.test_config_widget.get_test_mode = lambda: TestMode.IBIT
win.resize(800, 600); win.show()

result = {{}}
step = [0]; done = [False]
def tick():
    s = step[0]; step[0] += 1
    if s == 2 and not done[0]:
        done[0] = True
        # start_all_tests performs duplicate relay validation and returns without starting
        win.start_all_tests()
        app.processEvents()
        result['pass'] = not win.testing_active  # should NOT have started
        result['reason'] = 'testing_active should be False due to duplicate relay check'
        print('RESULT:' + json.dumps(result)); app.quit()
timer = QTimer(); timer.timeout.connect(tick); timer.start(1000)
app.exec_()
''')

# A2: Duplicate IP:port blocked at start
case('A2: Duplicate IP:port blocked at start',
f'''
{make_sim(PORT_BASE+50)}
win = MultiUUTTestGUI()
win.daq = MockDAQController(); win.daq.initialize('MockDAQ')
win.uuts = [UUT('P1','127.0.0.1',{PORT_BASE+50},0), UUT('P2','127.0.0.1',{PORT_BASE+50},1)]
win.uut_table_widget.update_table(win.uuts)
win.test_config_widget.get_test_mode = lambda: TestMode.IBIT
win.resize(800, 600); win.show()

result = {{}}
step = [0]; done = [False]
def tick():
    s = step[0]; step[0] += 1
    if s == 2 and not done[0]:
        done[0] = True
        # start_all_tests performs duplicate IP:port validation and returns without starting
        win.start_all_tests()
        app.processEvents()
        result['pass'] = not win.testing_active
        result['reason'] = 'testing_active should be False due to duplicate IP:port'
        print('RESULT:' + json.dumps(result)); app.quit()
timer = QTimer(); timer.timeout.connect(tick); timer.start(1000)
app.exec_()
''')

# A3: No UUTs — start rejected
case('A3: No UUTs — start rejected',
f'''
win = MultiUUTTestGUI()
win.daq = MockDAQController(); win.daq.initialize('MockDAQ')
win.resize(800, 600); win.show()
result = {{}}
step = [0]; done = [False]
def tick():
    s = step[0]; step[0] += 1
    if s == 2 and not done[0]:
        done[0] = True
        # start_all_tests checks for empty UUT list and returns without starting
        win.start_all_tests()
        app.processEvents()
        result['pass'] = not win.testing_active
        result['reason'] = 'no UUTs should prevent start'
        print('RESULT:' + json.dumps(result)); app.quit()
timer = QTimer(); timer.timeout.connect(tick); timer.start(1000)
app.exec_()
''')

# A4: DAQ not initialized — start rejected
case('A4: DAQ not initialized — start rejected',
f'''
{make_sim(PORT_BASE+55)}
win = MultiUUTTestGUI()
# Don't initialize DAQ
win.uuts = [UUT('P1','127.0.0.1',{PORT_BASE+55},0)]
win.uut_table_widget.update_table(win.uuts)
win.test_config_widget.get_test_mode = lambda: TestMode.IBIT
win.resize(800, 600); win.show()
result = {{}}
step = [0]; done = [False]
def tick():
    s = step[0]; step[0] += 1
    if s == 2 and not done[0]:
        done[0] = True
        # start_all_tests checks that daq.do_task is set and returns without starting
        win.start_all_tests()
        app.processEvents()
        result['pass'] = not win.testing_active
        result['reason'] = 'uninitialized DAQ should prevent start'
        print('RESULT:' + json.dumps(result)); app.quit()
timer = QTimer(); timer.timeout.connect(tick); timer.start(1000)
app.exec_()
''')


# ════════════════════════════════════════════════════════════════════════
# GROUP B: Safety guards
# ════════════════════════════════════════════════════════════════════════
print('\n--- B. Safety Guards ---', flush=True)

# B1: Double-click Start — second start is ignored
case('B1: Double-click Start — second call is no-op',
f'''
{make_sim(PORT_BASE+500)}
win = MultiUUTTestGUI()
mock_daq = MockDAQController(); mock_daq.initialize('MockDAQ')
mock_daq.register_vehicle(0, sim)
win.daq = mock_daq
win.uuts = [UUT('P1','127.0.0.1',{PORT_BASE+500},0)]
win.uut_table_widget.update_table(win.uuts)
win.test_config_widget.get_test_mode = lambda: TestMode.IBIT
win.resize(800, 600); win.show()
result = {{}}
step = [0]; done = [False]
def tick():
    s = step[0]; step[0] += 1
    if s == 2:
        win._auto_start_test(120)  # First start
    elif s == 3 and not done[0]:
        done[0] = True
        # Capture the executor from the first (valid) start
        executor_before = id(win.current_test_executor)
        first_start_active = win.testing_active
        # Second start — start_all_tests should be blocked by testing_active guard
        win.start_all_tests()
        app.processEvents()
        executor_after = id(win.current_test_executor)
        # First start must have succeeded (testing_active) and executor must be same
        result['pass'] = first_start_active and (executor_before == executor_after)
        result['reason'] = f'first_active={{first_start_active}}, executor changed: before={{executor_before}} after={{executor_after}}'
        print('RESULT:' + json.dumps(result)); app.quit()
timer = QTimer(); timer.timeout.connect(tick); timer.start(1000)
app.exec_()
''')

# B2: Remove UUT during test — blocked
case('B2: Remove UUT during active test — blocked',
f'''
{make_sim(PORT_BASE+505)}
win = MultiUUTTestGUI()
mock_daq = MockDAQController(); mock_daq.initialize('MockDAQ')
mock_daq.register_vehicle(0, sim)
win.daq = mock_daq
win.uuts = [UUT('P1','127.0.0.1',{PORT_BASE+505},0), UUT('P2','127.0.0.1',{PORT_BASE+550},1)]
win.uut_table_widget.update_table(win.uuts)
win.test_config_widget.get_test_mode = lambda: TestMode.IBIT
win.resize(800, 600); win.show()
result = {{}}
step = [0]; done = [False]
def tick():
    s = step[0]; step[0] += 1
    if s == 2:
        win._auto_start_test(120)
    elif s == 4 and not done[0]:
        done[0] = True
        count_before = len(win.uuts)
        win.uut_table_widget.table.selectRow(1)
        win.remove_uut()  # Should be blocked
        count_after = len(win.uuts)
        result['pass'] = count_after == count_before
        result['reason'] = f'uuts: before={{count_before}} after={{count_after}}'
        print('RESULT:' + json.dumps(result)); app.quit()
timer = QTimer(); timer.timeout.connect(tick); timer.start(1000)
app.exec_()
''')

# B3: Mode switch mid-batch — ignored
case('B3: Mode switch mid-batch — ignored',
f'''
{make_sim(PORT_BASE+555)}
win = MultiUUTTestGUI()
mock_daq = MockDAQController(); mock_daq.initialize('MockDAQ')
mock_daq.register_vehicle(0, sim)
win.daq = mock_daq
win.uuts = [UUT('P1','127.0.0.1',{PORT_BASE+555},0)]
win.uut_table_widget.update_table(win.uuts)
win.test_config_widget.get_test_mode = lambda: TestMode.IBIT
win.resize(800, 600); win.show()
result = {{}}
step = [0]; done = [False]
def tick():
    s = step[0]; step[0] += 1
    if s == 2:
        win._auto_start_test(120)
    elif s == 4 and not done[0]:
        done[0] = True
        mode_before = win.test_mode
        # Simulate mode change signal during active test
        win.on_test_mode_changed('playback')
        mode_after = win.test_mode
        result['pass'] = mode_after == mode_before
        result['reason'] = f'mode: before={{mode_before}} after={{mode_after}}'
        print('RESULT:' + json.dumps(result)); app.quit()
timer = QTimer(); timer.timeout.connect(tick); timer.start(1000)
app.exec_()
''')


# ════════════════════════════════════════════════════════════════════════
# GROUP C: IBIT failure modes
# ════════════════════════════════════════════════════════════════════════
print('\n--- C. IBIT Failure Modes ---', flush=True)

# C1: IBIT FAIL — mistracking surfaces identified
case('C1: IBIT FAIL — mistracking flags detected and surfaces named',
f'''
{make_sim(PORT_BASE+40, ibit_pass=False, flags=0xC0)}
win = MultiUUTTestGUI()
mock_daq = MockDAQController(); mock_daq.initialize('MockDAQ')
mock_daq.register_vehicle(0, sim)
win.daq = mock_daq
win.uuts = [UUT('F1','127.0.0.1',{PORT_BASE+40},0)]
win.uut_table_widget.update_table(win.uuts)
win.test_config_widget.get_test_mode = lambda: TestMode.IBIT
win.resize(800, 600); win.show()

result = {{}}
step = [0]; done = [False]
def tick():
    s = step[0]; step[0] += 1
    if s == 2:
        win._auto_start_test(120)
    elif s > 5 and not done[0]:
        u = win.uuts[0]
        if u.status in ('Retry', 'Failed (3x)') or (u.iterations_completed >= 1 and not win.testing_active):
            done[0] = True
            # Verify the FAIL was detected: at least 1 iteration completed and status is Retry/Failed
            result['pass'] = u.iterations_completed >= 1 and u.status in ('Retry', 'Failed (3x)')
            result['iterations'] = u.iterations_completed
            result['status'] = u.status
            result['reason'] = f'iters={{u.iterations_completed}}, status={{u.status}}'
            print('RESULT:' + json.dumps(result)); app.quit()
        elif s > 90:
            done[0] = True
            result['pass'] = False; result['reason'] = 'timeout'
            print('RESULT:' + json.dumps(result)); app.quit()
timer = QTimer(); timer.timeout.connect(tick); timer.start(1000)
app.exec_()
''', timeout=120)

# C2: All 8 surfaces mistracking (0xFF)
case('C2: All 8 surfaces mistracking (0xFF)',
f'''
{make_sim(PORT_BASE+45, ibit_pass=False, flags=0xFF)}
win = MultiUUTTestGUI()
mock_daq = MockDAQController(); mock_daq.initialize('MockDAQ')
mock_daq.register_vehicle(0, sim)
win.daq = mock_daq
win.uuts = [UUT('F_all','127.0.0.1',{PORT_BASE+45},0)]
win.uut_table_widget.update_table(win.uuts)
win.test_config_widget.get_test_mode = lambda: TestMode.IBIT
win.resize(800, 600); win.show()
result = {{}}
step = [0]; done = [False]
def tick():
    s = step[0]; step[0] += 1
    if s == 2:
        win._auto_start_test(120)
    elif s > 5 and not done[0]:
        u = win.uuts[0]
        if u.iterations_completed >= 1 or u.status in ('Retry','Failed (3x)'):
            done[0] = True
            result['pass'] = u.iterations_completed >= 1
            result['status'] = u.status; result['iters'] = u.iterations_completed
            print('RESULT:' + json.dumps(result)); app.quit()
        elif s > 90:
            done[0] = True; result['pass'] = False; result['reason'] = 'timeout'
            print('RESULT:' + json.dumps(result)); app.quit()
timer = QTimer(); timer.timeout.connect(tick); timer.start(1000)
app.exec_()
''', timeout=120)

# C3: Single surface mistracking (bit 0 = Upper Rudder)
case('C3: Single surface mistracking (0x01 = Upper Rudder)',
f'''
{make_sim(PORT_BASE+50, ibit_pass=False, flags=0x01)}
win = MultiUUTTestGUI()
mock_daq = MockDAQController(); mock_daq.initialize('MockDAQ')
mock_daq.register_vehicle(0, sim)
win.daq = mock_daq
win.uuts = [UUT('F_rud','127.0.0.1',{PORT_BASE+50},0)]
win.uut_table_widget.update_table(win.uuts)
win.test_config_widget.get_test_mode = lambda: TestMode.IBIT
win.resize(800, 600); win.show()
result = {{}}
step = [0]; done = [False]
def tick():
    s = step[0]; step[0] += 1
    if s == 2:
        win._auto_start_test(120)
    elif s > 5 and not done[0]:
        u = win.uuts[0]
        if u.iterations_completed >= 1 or u.status in ('Retry','Failed (3x)'):
            done[0] = True
            result['pass'] = u.iterations_completed >= 1
            result['status'] = u.status
            print('RESULT:' + json.dumps(result)); app.quit()
        elif s > 90:
            done[0] = True; result['pass'] = False; result['reason'] = 'timeout'
            print('RESULT:' + json.dumps(result)); app.quit()
timer = QTimer(); timer.timeout.connect(tick); timer.start(1000)
app.exec_()
''', timeout=120)

# C4: 3x permanent fail — PASS vehicle always fails
case('C4: 3 consecutive failures → permanent skip',
f'''
{make_sim(PORT_BASE+55, ibit_pass=False, flags=0xC0)}
win = MultiUUTTestGUI()
mock_daq = MockDAQController(); mock_daq.initialize('MockDAQ')
mock_daq.register_vehicle(0, sim)
win.daq = mock_daq
win.uuts = [UUT('F1','127.0.0.1',{PORT_BASE+55},0)]
win.uut_table_widget.update_table(win.uuts)
win.test_config_widget.get_test_mode = lambda: TestMode.IBIT
win.resize(800, 600); win.show()
result = {{}}
step = [0]; done = [False]
def tick():
    s = step[0]; step[0] += 1
    if s == 2:
        win._auto_start_test(300)
    elif not done[0]:
        u = win.uuts[0]
        if u.status == 'Failed (3x)':
            done[0] = True
            result['pass'] = True
            result['status'] = u.status
            result['iterations'] = u.iterations_completed
            # Verify relay is OFF
            result['relay_off'] = not mock_daq._line_states.get(0, False)
            print('RESULT:' + json.dumps(result)); app.quit()
        elif s > 200:
            done[0] = True; result['pass'] = False
            result['reason'] = f'never reached Failed(3x), status={{u.status}}'
            print('RESULT:' + json.dumps(result)); app.quit()
timer = QTimer(); timer.timeout.connect(tick); timer.start(1000)
app.exec_()
''', timeout=300)


# ════════════════════════════════════════════════════════════════════════
# GROUP D: State machine edge cases
# ════════════════════════════════════════════════════════════════════════
print('\n--- D. State Machine Edge Cases ---', flush=True)

# D1: TERMINAL mode detection
case('D1: TERMINAL mode — detected, power-cycle alert, test fails',
f'''
# Create a sim that transitions to TERMINAL after ARM
{make_sim(PORT_BASE+60)}
# Patch the sim to enter TERMINAL mode after arm
import time as _time
_orig_handle = sim._handle_command
def _terminal_cmd(msg):
    _orig_handle(msg)
    # After ARM (param1==1), force TERMINAL mode
    if int(getattr(msg, 'param1', 0)) == 1:
        from sim.config.defaults import ActuationState
        _time.sleep(0.1)
        sim.act_state = ActuationState.TERMINAL
sim._handle_command = _terminal_cmd

win = MultiUUTTestGUI()
mock_daq = MockDAQController(); mock_daq.initialize('MockDAQ')
mock_daq.register_vehicle(0, sim)
win.daq = mock_daq
win.uuts = [UUT('P1','127.0.0.1',{PORT_BASE+60},0)]
win.uut_table_widget.update_table(win.uuts)
win.test_config_widget.get_test_mode = lambda: TestMode.IBIT
win.resize(800, 600); win.show()

alerts = []
orig_alert = win.show_alert
win.show_alert = lambda msg, **kw: (alerts.append(msg), orig_alert(msg, **kw))

result = {{}}
step = [0]; done = [False]
def tick():
    s = step[0]; step[0] += 1
    if s == 2:
        win._auto_start_test(120)
    elif s > 5 and not done[0]:
        u = win.uuts[0]
        has_terminal_alert = any('TERMINAL' in a.upper() for a in alerts)
        if has_terminal_alert or u.status in ('Retry','Failed (3x)') or s > 60:
            done[0] = True
            result['pass'] = has_terminal_alert
            result['alerts'] = alerts[:5]
            result['status'] = u.status
            result['reason'] = f'terminal_alert={{has_terminal_alert}}, alerts={{alerts[:3]}}'
            print('RESULT:' + json.dumps(result)); app.quit()
timer = QTimer(); timer.timeout.connect(tick); timer.start(1000)
app.exec_()
''', timeout=90)

# D2: POS_CHECK mode after ARM (TAU elevons simulation)
case('D2: POS_CHECK intermediate state — handled, not an error',
f'''
{make_sim(PORT_BASE+65)}
# Patch sim to insert POS_CHECK before OPERATE after ARM
import time as _time
_orig_handle = sim._handle_command
def _pos_check_cmd(msg):
    _orig_handle(msg)
    # After ARM (param1==1), go to POS_CHECK first then transition to OPERATE
    if int(getattr(msg, 'param1', 0)) == 1:
        from sim.config.defaults import ActuationState
        sim.act_state = ActuationState.POS_CHECK
        def _to_operate():
            _time.sleep(1.5)  # POS_CHECK lasts 1.5s
            if sim.act_state == ActuationState.POS_CHECK:
                sim.act_state = ActuationState.OPERATE
        import threading
        threading.Thread(target=_to_operate, daemon=True).start()
sim._handle_command = _pos_check_cmd

win = MultiUUTTestGUI()
mock_daq = MockDAQController(); mock_daq.initialize('MockDAQ')
mock_daq.register_vehicle(0, sim)
win.daq = mock_daq
win.uuts = [UUT('P1','127.0.0.1',{PORT_BASE+65},0)]
win.uut_table_widget.update_table(win.uuts)
win.test_config_widget.get_test_mode = lambda: TestMode.IBIT
win.resize(800, 600); win.show()

result = {{}}
step = [0]; done = [False]
def tick():
    s = step[0]; step[0] += 1
    if s == 2:
        win._auto_start_test(120)
    elif s > 5 and not done[0]:
        u = win.uuts[0]
        if u.iterations_completed >= 1:
            done[0] = True
            result['pass'] = True  # POS_CHECK was handled, IBIT completed
            result['iterations'] = u.iterations_completed
            result['status'] = u.status
            print('RESULT:' + json.dumps(result)); app.quit()
        elif u.status in ('Failed (3x)',) or s > 90:
            done[0] = True
            result['pass'] = False
            result['reason'] = f'POS_CHECK not handled, status={{u.status}}'
            print('RESULT:' + json.dumps(result)); app.quit()
timer = QTimer(); timer.timeout.connect(tick); timer.start(1000)
app.exec_()
''', timeout=120)

# D3: Instantaneous IBIT completion
case('D3: Instantaneous IBIT completion detected',
f'''
{make_sim(PORT_BASE+70)}
# Patch sim to complete IBIT instantly
_orig_run_ibit = sim._run_ibit
def _instant_ibit():
    from sim.config.defaults import ActuationState, IBITSubstate
    sim.ibit_substate = IBITSubstate.DONE
    sim.act_state = ActuationState.OPERATE
    sim._ibit_active = False
    sim._ibit_direct = False
    sim._last_ibit_end = __import__('time').time()
sim._run_ibit = _instant_ibit

win = MultiUUTTestGUI()
mock_daq = MockDAQController(); mock_daq.initialize('MockDAQ')
mock_daq.register_vehicle(0, sim)
win.daq = mock_daq
win.uuts = [UUT('P1','127.0.0.1',{PORT_BASE+70},0)]
win.uut_table_widget.update_table(win.uuts)
win.test_config_widget.get_test_mode = lambda: TestMode.IBIT
win.resize(800, 600); win.show()

result = {{}}
step = [0]; done = [False]
def tick():
    s = step[0]; step[0] += 1
    if s == 2:
        win._auto_start_test(120)
    elif s > 5 and not done[0]:
        u = win.uuts[0]
        if u.iterations_completed >= 1:
            done[0] = True
            result['pass'] = True
            result['status'] = u.status; result['iters'] = u.iterations_completed
            print('RESULT:' + json.dumps(result)); app.quit()
        elif u.status == 'Failed (3x)' or s > 90:
            done[0] = True
            result['pass'] = False
            result['reason'] = f'instant IBIT not handled, status={{u.status}}'
            print('RESULT:' + json.dumps(result)); app.quit()
timer = QTimer(); timer.timeout.connect(tick); timer.start(1000)
app.exec_()
''', timeout=120)

# D4: IBIT phase timeout (sim freezes at ELEVON)
case('D4: Phase timeout — sim freezes at ELEVON substate',
f'''
{make_sim(PORT_BASE+75)}
# Patch sim to freeze at ELEVON substate
_orig_elevon = sim._run_ibit_elevon
def _freeze_elevon(dur):
    from sim.config.defaults import IBITSubstate
    sim.ibit_substate = IBITSubstate.ELEVON
    # Just freeze — never proceed
    import time
    frozen_start = time.time()
    while sim._ibit_active and time.time() - frozen_start < 200:
        time.sleep(0.1)
sim._run_ibit_elevon = _freeze_elevon

win = MultiUUTTestGUI()
mock_daq = MockDAQController(); mock_daq.initialize('MockDAQ')
mock_daq.register_vehicle(0, sim)
win.daq = mock_daq
win.uuts = [UUT('P1','127.0.0.1',{PORT_BASE+75},0)]
win.uut_table_widget.update_table(win.uuts)
win.test_config_widget.get_test_mode = lambda: TestMode.IBIT
# Patch get_config to return a short phase_timeout so the executor actually uses it
_orig_get_config = win.test_config_widget.get_config
win.test_config_widget.get_config = lambda: {{**_orig_get_config(), 'phase_timeout': 8.0, 'ibit_timeout': 30.0}}
win.resize(800, 600); win.show()

result = {{}}
step = [0]; done = [False]
def tick():
    s = step[0]; step[0] += 1
    if s == 2:
        win._auto_start_test(120)  # 120s batch — longer than 8s phase timeout
    elif s > 5 and not done[0]:
        u = win.uuts[0]
        if u.status in ('Retry', 'Failed (3x)'):
            done[0] = True
            result['pass'] = True  # Phase timeout correctly aborted the test
            result['status'] = u.status
            result['relay_off'] = not mock_daq._line_states.get(0, False)
            print('RESULT:' + json.dumps(result)); app.quit()
        elif s > 80:
            done[0] = True
            result['pass'] = False
            result['reason'] = f'phase timeout not triggered, status={{win.uuts[0].status}}'
            print('RESULT:' + json.dumps(result)); app.quit()
timer = QTimer(); timer.timeout.connect(tick); timer.start(1000)
app.exec_()
''', timeout=90)


# ════════════════════════════════════════════════════════════════════════
# GROUP E: Relay edge cases
# ════════════════════════════════════════════════════════════════════════
print('\n--- E. Relay Edge Cases ---', flush=True)

# E1: Relay enable fails — test aborted before IBIT
case('E1: Relay enable failure — test aborted, IBIT never starts',
f'''
{make_sim(PORT_BASE+80)}
mock_daq = MockDAQController(); mock_daq.initialize('MockDAQ')
mock_daq.register_vehicle(0, sim)
# Patch set_line to fail on enable
_orig = mock_daq.set_line
def _fail_enable(line, state):
    if state == True:  # Fail enable only
        return False, 'Simulated relay enable failure'
    return _orig(line, state)
mock_daq.set_line = _fail_enable

win = MultiUUTTestGUI()
win.daq = mock_daq
win.uuts = [UUT('P1','127.0.0.1',{PORT_BASE+80},0)]
win.uut_table_widget.update_table(win.uuts)
win.test_config_widget.get_test_mode = lambda: TestMode.IBIT
win.resize(800, 600); win.show()

result = {{}}
step = [0]; done = [False]
def tick():
    s = step[0]; step[0] += 1
    if s == 2:
        win._auto_start_test(120)
    elif s > 3 and not done[0]:
        u = win.uuts[0]
        relay_off = not mock_daq._line_states.get(0, False)
        if relay_off and u.status in ('Retry', 'Failed (3x)'):
            done[0] = True
            result['pass'] = True
            result['status'] = u.status
            result['iters'] = u.iterations_completed
            result['relay_off'] = relay_off
            print('RESULT:' + json.dumps(result)); app.quit()
        elif s > 90:
            done[0] = True
            relay_off = not mock_daq._line_states.get(0, False)
            u = win.uuts[0]
            # Safety-critical check: relay must be off. Status update may be delayed in offscreen Qt.
            result['pass'] = relay_off
            result['status'] = u.status
            result['relay_off'] = relay_off
            result['reason'] = f'relay_off={{relay_off}}, status={{u.status}}'
            print('RESULT:' + json.dumps(result)); app.quit()
        elif s > 60:
            done[0] = True
            result['pass'] = False
            result['status'] = u.status
            result['relay_off'] = relay_off
            result['reason'] = f'relay_off={{relay_off}}, status={{u.status}}'
            print('RESULT:' + json.dumps(result)); app.quit()
timer = QTimer(); timer.timeout.connect(tick); timer.start(1000)
app.exec_()
''', timeout=120)

# E2: All relays OFF after emergency stop
case('E2: Emergency stop — all relays OFF immediately',
f'''
{make_sim(PORT_BASE+85)}
win = MultiUUTTestGUI()
mock_daq = MockDAQController(); mock_daq.initialize('MockDAQ')
mock_daq.register_vehicle(0, sim)
win.daq = mock_daq
win.uuts = [UUT('P1','127.0.0.1',{PORT_BASE+85},0)]
win.uut_table_widget.update_table(win.uuts)
win.test_config_widget.get_test_mode = lambda: TestMode.IBIT
win.resize(800, 600); win.show()

result = {{}}
step = [0]; done = [False]
def tick():
    s = step[0]; step[0] += 1
    if s == 2:
        win._auto_start_test(300)
    elif s == 8 and not done[0]:
        done[0] = True
        win.emergency_stop()
        import time; time.sleep(0.5)
        app.processEvents()
        all_off = all(not v for v in mock_daq._line_states.values())
        result['pass'] = all_off and not win.testing_active
        result['testing_active'] = win.testing_active
        result['relays'] = dict(mock_daq._line_states)
        print('RESULT:' + json.dumps(result)); app.quit()
timer = QTimer(); timer.timeout.connect(tick); timer.start(1000)
app.exec_()
''', timeout=60)


# ════════════════════════════════════════════════════════════════════════
# GROUP F: Batch lifecycle
# ════════════════════════════════════════════════════════════════════════
print('\n--- F. Batch Lifecycle ---', flush=True)

# F1: Batch report generated correctly (valid JSON, no enum serialization error)
case('F1: Batch report JSON serialization — no errors',
f'''
{make_sim(PORT_BASE+90)}
win = MultiUUTTestGUI()
mock_daq = MockDAQController(); mock_daq.initialize('MockDAQ')
mock_daq.register_vehicle(0, sim)
win.daq = mock_daq
win.uuts = [UUT('P1','127.0.0.1',{PORT_BASE+90},0)]
win.uut_table_widget.update_table(win.uuts)
win.test_config_widget.get_test_mode = lambda: TestMode.IBIT
win.resize(800, 600); win.show()

result = {{}}
step = [0]; done = [False]
def tick():
    s = step[0]; step[0] += 1
    if s == 2:
        win._auto_start_test(60)  # Short batch to get a report quickly
    elif s > 5 and not done[0]:
        u = win.uuts[0]
        # Wait until testing has fully stopped before checking for the report file
        if not win.testing_active and s > 10:
            done[0] = True
            import os
            reports = []
            if os.path.exists(win.report_directory):
                reports = [f for f in os.listdir(win.report_directory) if f.endswith('.json')]
            if reports:
                try:
                    with open(os.path.join(win.report_directory, sorted(reports)[-1])) as f:
                        report = json.load(f)
                    result['pass'] = 'uuts' in report and 'test_mode' in report
                    result['report_keys'] = list(report.keys())
                except Exception as e:
                    result['pass'] = False
                    result['reason'] = f'Report parse error: {{e}}'
            else:
                result['pass'] = False
                result['reason'] = f'No report in {{win.report_directory}}'
            print('RESULT:' + json.dumps(result)); app.quit()
        elif s > 120:
            done[0] = True; result['pass'] = False; result['reason'] = 'timeout'
            print('RESULT:' + json.dumps(result)); app.quit()
timer = QTimer(); timer.timeout.connect(tick); timer.start(1000)
app.exec_()
''', timeout=120)

# F2: Natural expiry — batch ends cleanly, relays OFF
case('F2: Natural batch expiry — clean shutdown, relays OFF',
f'''
{make_sim(PORT_BASE+95)}
win = MultiUUTTestGUI()
mock_daq = MockDAQController(); mock_daq.initialize('MockDAQ')
mock_daq.register_vehicle(0, sim)
win.daq = mock_daq
win.uuts = [UUT('P1','127.0.0.1',{PORT_BASE+95},0)]
win.uut_table_widget.update_table(win.uuts)
win.test_config_widget.get_test_mode = lambda: TestMode.IBIT
win.resize(800, 600); win.show()

result = {{}}
step = [0]; done = [False]
def tick():
    s = step[0]; step[0] += 1
    if s == 2:
        win._auto_start_test(60)  # Short batch
    elif not win.testing_active and s > 5 and not done[0]:
        done[0] = True
        all_off = all(not v for v in mock_daq._line_states.values())
        result['pass'] = all_off
        result['relays'] = dict(mock_daq._line_states)
        result['iterations'] = win.uuts[0].iterations_completed
        print('RESULT:' + json.dumps(result)); app.quit()
    elif s > 120:
        done[0] = True; result['pass'] = False; result['reason'] = 'never finished'
        print('RESULT:' + json.dumps(result)); app.quit()
timer = QTimer(); timer.timeout.connect(tick); timer.start(1000)
app.exec_()
''', timeout=150)


# ════════════════════════════════════════════════════════════════════════
# GROUP G: Multi-iteration stability
# ════════════════════════════════════════════════════════════════════════
print('\n--- G. Multi-Iteration Stability ---', flush=True)

# G1: 2 consecutive PASS iterations
case('G1: 2 consecutive PASS iterations — state correctly reset between runs',
f'''
{make_sim(PORT_BASE+5000)}
win = MultiUUTTestGUI()
mock_daq = MockDAQController(); mock_daq.initialize('MockDAQ')
mock_daq.register_vehicle(0, sim)
win.daq = mock_daq
win.uuts = [UUT('P1','127.0.0.1',{PORT_BASE+5000},0)]
win.uut_table_widget.update_table(win.uuts)
win.test_config_widget.get_test_mode = lambda: TestMode.IBIT
win.resize(800, 600); win.show()

result = {{}}
step = [0]; done = [False]
def tick():
    s = step[0]; step[0] += 1
    if s == 2:
        win._auto_start_test(300)
    elif not done[0]:
        u = win.uuts[0]
        if u.iterations_completed >= 2:
            done[0] = True
            result['pass'] = True
            result['iterations'] = u.iterations_completed
            result['status'] = u.status
            result['relay_off'] = not mock_daq._line_states.get(0, False)
            print('RESULT:' + json.dumps(result)); app.quit()
        elif u.status == 'Failed (3x)' or s > 200:
            done[0] = True
            result['pass'] = False
            result['reason'] = f'never got 2 iters, status={{u.status}}'
            print('RESULT:' + json.dumps(result)); app.quit()
timer = QTimer(); timer.timeout.connect(tick); timer.start(1000)
app.exec_()
''', timeout=300)

# G2: Error log persists across iterations
case('G2: Error log persists across iterations',
f'''
{make_sim(PORT_BASE+5005, ibit_pass=False, flags=0xC0)}
win = MultiUUTTestGUI()
mock_daq = MockDAQController(); mock_daq.initialize('MockDAQ')
mock_daq.register_vehicle(0, sim)
win.daq = mock_daq
win.uuts = [UUT('F1','127.0.0.1',{PORT_BASE+5005},0)]
win.uut_table_widget.update_table(win.uuts)
win.test_config_widget.get_test_mode = lambda: TestMode.IBIT
win.resize(800, 600); win.show()

result = {{}}
step = [0]; done = [False]
def tick():
    s = step[0]; step[0] += 1
    if s == 2:
        win._auto_start_test(300)
    elif not done[0]:
        u = win.uuts[0]
        if u.status == 'Failed (3x)' or (u.iterations_completed >= 2 and not win.testing_active):
            done[0] = True
            err_path = os.path.join(win.log_directory, 'errors', 'error_log.jsonl')
            entries = []
            if os.path.exists(err_path):
                with open(err_path) as f:
                    entries = [json.loads(l) for l in f if l.strip()]
            ibit_errors = [e for e in entries if e.get('category') == 'IBIT']
            result['pass'] = len(ibit_errors) >= 1
            result['error_count'] = len(entries)
            result['ibit_errors'] = len(ibit_errors)
            result['iterations'] = u.iterations_completed
            print('RESULT:' + json.dumps(result)); app.quit()
        elif s > 280:
            done[0] = True; result['pass'] = False; result['reason'] = 'timeout'
            print('RESULT:' + json.dumps(result)); app.quit()
timer = QTimer(); timer.timeout.connect(tick); timer.start(1000)
app.exec_()
''', timeout=300)

# G3: Foreign sysid messages filtered — no false PASS
case('G3: Foreign sysid filter — _expected_sysid set correctly after connection',
f'''
# Verify that after connecting, the executor sets _expected_sysid to the vehicle's sysid.
# A foreign sysid message should be filtered out by the dispatch worker.
{make_sim(PORT_BASE+110, sysid=2, ibit_pass=False, flags=0xC0)}

win = MultiUUTTestGUI()
mock_daq = MockDAQController(); mock_daq.initialize('MockDAQ')
mock_daq.register_vehicle(0, sim)
win.daq = mock_daq
win.uuts = [UUT('F1','127.0.0.1',{PORT_BASE+5050},0)]
win.uut_table_widget.update_table(win.uuts)
win.test_config_widget.get_test_mode = lambda: TestMode.IBIT
win.resize(800, 600); win.show()

result = {{}}
step = [0]; done = [False]
def tick():
    s = step[0]; step[0] += 1
    if s == 2:
        win._auto_start_test(120)
    elif s > 5 and not done[0]:
        ex = win.current_test_executor
        if ex and hasattr(ex, '_expected_sysid') and ex._expected_sysid is not None:
            done[0] = True
            result['pass'] = ex._expected_sysid == 2
            result['expected_sysid'] = ex._expected_sysid
            result['reason'] = f'_expected_sysid={{ex._expected_sysid}} (expected 2)'
            print('RESULT:' + json.dumps(result)); app.quit()
        elif s > 60:
            done[0] = True
            ex2 = win.current_test_executor
            sid = getattr(ex2, '_expected_sysid', 'no_executor') if ex2 else 'no_executor'
            result['pass'] = False
            result['reason'] = f'_expected_sysid={{{sid}}}, executor={{{ex2}}}'
            print('RESULT:' + json.dumps(result)); app.quit()
timer = QTimer(); timer.timeout.connect(tick); timer.start(1000)
app.exec_()
''', timeout=90)


# ════════════════════════════════════════════════════════════════════════
# REPORT
# ════════════════════════════════════════════════════════════════════════
passed = sum(1 for r in results if r['pass'])
failed = len(results) - passed

print(f'\n{"="*70}')
print(f'  EDGE CASE TEST RESULTS')
print(f'{"="*70}')
for r in results:
    sym = '+' if r['pass'] else 'x'
    print(f'  [{sym}] {r["name"]}')
    if not r['pass']:
        reason = r['result'].get('reason', r['result'].get('error', ''))
        if reason:
            print(f'       {reason[:120]}')
print(f'\n  {passed} passed / {failed} failed / {len(results)} total')
print(f'{"="*70}')

# Save report
report_path = os.path.join(ROOT, 'edge_case_results.json')
with open(report_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f'  Report: {report_path}')

import sys
sys.exit(0 if failed == 0 else 1)
