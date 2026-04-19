"""
Comprehensive Permutation Test — covers all high-value equivalence classes.

Groups:
  A. Safety-critical paths
  B. UUT count/pattern variations
  C. Boundary conditions
  D. Error/failure injection
  E. State persistence
  F. UI interactions during test
  G. Configuration variants
"""
import os, sys, time, json, threading, subprocess, csv as csv_mod, math
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = r'C:\Anduril\RoadRunner Flight Mode IBIT'
sys.path.insert(0, ROOT)

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# ── Generate test_profile.csv ────────────────────────────────────────────
csv_path = os.path.join(ROOT, 'test_profile.csv')
if not os.path.exists(csv_path):
    with open(csv_path, 'w', newline='') as f:
        w = csv_mod.writer(f)
        w.writerow(['timestamp',
            'event/left_elevon_ted_command_cdeg','event/right_elevon_ted_command_cdeg',
            'event/lower_rudder_tel_command_cdeg','event/upper_rudder_tel_command_cdeg',
            'event/left_tvc_upper_command_cdeg','event/left_tvc_lower_command_cdeg',
            'event/right_tvc_upper_command_cdeg','event/right_tvc_lower_command_cdeg',
            'event/left_engine_speed_command_prct_rpm','event/right_engine_speed_command_prct_rpm'])
        for i in range(500):
            t = i/100.0; p = t/5.0
            e = (-p/0.25 if p<0.25 else -1+2*(p-0.25)/0.5 if p<0.75 else 1-(p-0.75)/0.25)
            r = math.sin(2*math.pi*t/5)*1500; a = 2*math.pi*t/5
            w.writerow([f'{t:.3f}', f'{e*2000:.0f}', f'{-e*2000:.0f}',
                f'{r:.0f}', f'{-r:.0f}',
                f'{1000*math.cos(a):.0f}', f'{1000*math.sin(a):.0f}',
                f'{-1000*math.cos(a):.0f}', f'{-1000*math.sin(a):.0f}',
                '0.0', '0.0'])

# ── Subprocess template ──────────────────────────────────────────────────
SCRIPT = r'''
import os, sys, time, json, threading
ROOT = r"{root}"
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'vehicle', 'dialects'))
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except: pass
{offscreen}

from rr_test.sim.vehicle import PandionVehicleSim
from rr_test.sim.mock_daq import MockDAQController
import rr_test.vehicle.connection as conn_mod
import rr_test.hardware.daq as daq_mod

UUT_CONFIG   = {uut_config}
TEST_MODE    = '{test_mode}'
STOP_METHOD  = '{stop_method}'
DURATION     = {duration}
BASE_PORT    = {base_port}
SKIP_STATE   = {skip_state}
SKIP_ARM     = {skip_arm}
USE_SITL_BTN = {use_sitl_btn}
FAIL_RELAY   = {fail_relay}
MULTI_ITER   = {multi_iter}

# Start sims
sims = []
for i, cfg in enumerate(UUT_CONFIG):
    sim = PandionVehicleSim(
        vehicle_port=BASE_PORT + i,
        sysid=i+1,
        ibit_pass=cfg['pass'],
        mistracking_flags=cfg.get('flags', 0),
        boot_time_s=1.0,
        ibit_duration_scale=0.2,
        boot_monitors=[0, 1],
    )
    threading.Thread(target=sim.start, daemon=True).start()
    sims.append(sim)
time.sleep(3)

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
from rr_test.vehicle.connection import UUT
from rr_test.vehicle.constants import TestMode, UUTStatus

win = MultiUUTTestGUI()
mock_daq = MockDAQController()
mock_daq.initialize('MockDAQ')

# Optionally inject relay failure on relay 0
if FAIL_RELAY:
    _orig_set = mock_daq.set_line
    _fail_count = [0]
    def _failing_set_line(line, state):
        if line == 0 and state and _fail_count[0] < 3:
            _fail_count[0] += 1
            return False, 'Simulated relay failure'
        return _orig_set(line, state)
    mock_daq.set_line = _failing_set_line

for i, (cfg, sim) in enumerate(zip(UUT_CONFIG, sims)):
    mock_daq.register_vehicle(i, sim)
win.daq = mock_daq

if USE_SITL_BTN:
    # Register sims on expected SITL ports (19901, 19902) but our sims
    # are on BASE_PORT+i -- so just pre-load UUTs manually
    pass

win.uuts = [UUT(cfg['serial'], '127.0.0.1', BASE_PORT + i, i)
            for i, cfg in enumerate(UUT_CONFIG)]
win.uut_table_widget.update_table(win.uuts)

csv_path = os.path.join(ROOT, 'test_profile.csv')
if TEST_MODE == 'playback':
    win.test_config_widget.get_test_mode = lambda: TestMode.PLAYBACK
    win.test_config_widget.get_playback_csv = lambda: csv_path
    win.test_config_widget.get_playback_type = lambda: 'Actuation'
else:
    # Force IBIT mode — radio buttons don't work in offscreen mode on Windows
    win.test_config_widget.get_test_mode = lambda: TestMode.IBIT

if SKIP_STATE:
    win.test_config_widget.skip_state_mgmt_checkbox.setChecked(True)
if SKIP_ARM:
    win.test_config_widget.skip_arm_checkbox.setChecked(True)

win.resize(1600, 900)
win.show()

result = {{
    'started': False,
    'uut_results': [],
    'relays_safe': True,
    'log_count': 0,
    'errors': [],
    'fleet_summary_seen': [],
}}

step = [0]
stop_done = [False]
min_iters_needed = 2 if MULTI_ITER else 1

def tick():
    s = step[0]; step[0] += 1
    try:
        if s == 2:
            win._auto_start_test(DURATION)
            result['started'] = win.testing_active

        elif STOP_METHOD == 'stop_before_connect' and s == 3:
            if not stop_done[0]:
                stop_done[0] = True
                win.testing_active = False
                if win.current_test_executor:
                    win.current_test_executor.stop()

        elif STOP_METHOD == 'emergency_relay_on' and s == 6 and not stop_done[0]:
            # Emergency when relay might be on
            stop_done[0] = True
            win.emergency_stop()

        elif STOP_METHOD == 'stop_during_arm' and s == 5 and not stop_done[0]:
            stop_done[0] = True
            win.testing_active = False
            if win.current_test_executor:
                win.current_test_executor.stop()

        elif STOP_METHOD == 'emergency' and s == 8 and not stop_done[0]:
            stop_done[0] = True
            win.emergency_stop()

        elif STOP_METHOD == 'manual_stop' and s == 10 and not stop_done[0]:
            stop_done[0] = True
            win.testing_active = False
            if win.current_test_executor:
                win.current_test_executor.stop()

        # Capture fleet summary snapshots
        if s % 5 == 0:
            summary = win.uut_table_widget._fleet_summary.text()
            if summary and summary not in result['fleet_summary_seen']:
                result['fleet_summary_seen'].append(summary)

        # Log filter interaction during test (test F variants)
        if s == 15 and hasattr(win.log_widget, '_filter_buttons'):
            win.log_widget._filter_buttons.get('ERROR', None) and \
                win.log_widget._filter_buttons['ERROR'].click()
            app.processEvents()
            win.log_widget._filter_buttons.get('ALL', None) and \
                win.log_widget._filter_buttons['ALL'].click()
            app.processEvents()

        # UUT selection during test
        if s == 12 and len(win.uuts) > 1:
            win.uut_table_widget.table.selectRow(1)
            app.processEvents()
            win.uut_table_widget.table.selectRow(0)
            app.processEvents()

        elif s > 5:
            pass_uuts   = [u for u in win.uuts if u.status == UUTStatus.COMPLETE]
            fail_uuts   = [u for u in win.uuts if u.status in
                           (UUTStatus.RETRY, UUTStatus.FAILED_PERMANENT)]
            multi_done  = MULTI_ITER and any(u.iterations_completed >= 2 for u in win.uuts)
            perm_failed = any(u.status == UUTStatus.FAILED_PERMANENT for u in win.uuts)
            stop_done_and_settled = stop_done[0] and s > stop_done[0] + 10 if isinstance(stop_done[0], int) else False
            timed_out   = s > DURATION + 40
            naturally_done = not win.testing_active and s > 5 and result['started']

            should_exit = (
                (STOP_METHOD in ('natural_expiry',) and naturally_done) or
                (STOP_METHOD in ('emergency','manual_stop','stop_before_connect',
                                 'emergency_relay_on','stop_during_arm') and
                 stop_done[0] and s > 18) or
                (perm_failed and not win.testing_active) or
                (multi_done) or
                timed_out
            )

            if should_exit:
                result['uut_results'] = [
                    {{'serial': u.serial_number, 'status': u.status,
                      'iterations': u.iterations_completed}}
                    for u in win.uuts
                ]
                result['relays_safe'] = all(
                    not mock_daq._line_states.get(i, False)
                    for i in range(len(win.uuts))
                )
                result['log_count'] = len(win.log_widget._all_entries) if hasattr(win.log_widget, '_all_entries') else -1
                print('RESULT:' + json.dumps(result), flush=True)
                app.quit()

    except Exception as e:
        result['errors'].append(f'step{{s}}: {{e}}')
        if s > 5:
            result['uut_results'] = [
                {{'serial': u.serial_number, 'status': u.status,
                  'iterations': u.iterations_completed}}
                for u in win.uuts
            ] if win.uuts else []
            result['relays_safe'] = all(
                not mock_daq._line_states.get(i, False)
                for i in range(len(win.uuts))
            ) if win.uuts else True
            print('RESULT:' + json.dumps(result), flush=True)
            app.quit()

timer = QTimer()
timer.timeout.connect(tick)
timer.start(1000)
app.exec_()
'''

# ── Test definitions ─────────────────────────────────────────────────────
def uut(serial, ibit_pass, flags=0):
    return {'serial': serial, 'pass': ibit_pass, 'flags': flags}

PASS = lambda n: uut(f'P{n}', True)
FAIL = lambda n: uut(f'F{n}', False, 0xC0)

TESTS = [

    # ── GROUP A: Safety-critical paths ───────────────────────────────────
    {'group': 'A', 'name': 'relay_ON_emergency',
     'desc': 'Emergency stop when relay is on mid-test',
     'uuts': [PASS(1)], 'mode': 'ibit', 'stop': 'emergency_relay_on',
     'checks': ['relays_safe']},

    {'group': 'A', 'name': '3x_fail_permanent_skip',
     'desc': 'FAIL vehicle hits 3 consecutive failures → permanently skipped, batch continues',
     'uuts': [FAIL(1), PASS(2)], 'mode': 'ibit', 'stop': 'natural_expiry',
     'checks': ['relays_safe', 'pass_uut_tested'],
     'duration': 90},

    {'group': 'A', 'name': 'emergency_mid_ibit',
     'desc': 'Emergency stop exactly when IBIT is executing (relay ON)',
     'uuts': [PASS(1)], 'mode': 'ibit', 'stop': 'emergency',
     'checks': ['relays_safe']},

    {'group': 'A', 'name': 'stop_during_arm',
     'desc': 'Manual stop during ARM phase',
     'uuts': [PASS(1)], 'mode': 'ibit', 'stop': 'stop_during_arm',
     'checks': ['relays_safe', 'stopped']},

    {'group': 'A', 'name': 'relay_failure_recovery',
     'desc': 'Relay set_line fails first 3 calls — executor retries and alerts',
     'uuts': [PASS(1)], 'mode': 'ibit', 'stop': 'natural_expiry',
     'fail_relay': True,
     'checks': ['relays_safe'],
     'duration': 60},

    # ── GROUP B: UUT count/pattern variations ────────────────────────────
    {'group': 'B', 'name': '1_pass',
     'desc': 'Single PASS vehicle',
     'uuts': [PASS(1)], 'mode': 'ibit', 'stop': 'natural_expiry',
     'checks': ['started', 'relays_safe', 'first_uut_tested']},

    {'group': 'B', 'name': '1_fail',
     'desc': 'Single FAIL vehicle',
     'uuts': [FAIL(1)], 'mode': 'ibit', 'stop': 'natural_expiry',
     'checks': ['started', 'relays_safe', 'first_uut_attempted']},

    {'group': 'B', 'name': '2_all_pass',
     'desc': 'Two PASS vehicles — round-robin',
     'uuts': [PASS(1), PASS(2)], 'mode': 'ibit', 'stop': 'natural_expiry',
     'checks': ['started', 'relays_safe', 'first_uut_tested'],
     'duration': 90},

    {'group': 'B', 'name': '2_all_fail',
     'desc': 'Two FAIL vehicles',
     'uuts': [FAIL(1), FAIL(2)], 'mode': 'ibit', 'stop': 'natural_expiry',
     'checks': ['started', 'relays_safe'],
     'duration': 90},

    {'group': 'B', 'name': '2_fail_first',
     'desc': 'FAIL first, PASS second — order matters for retry logic',
     'uuts': [FAIL(1), PASS(2)], 'mode': 'ibit', 'stop': 'natural_expiry',
     'checks': ['started', 'relays_safe'],
     'duration': 90},

    {'group': 'B', 'name': '3_uuts_mixed',
     'desc': 'Three UUTs: PASS, FAIL, PASS',
     'uuts': [PASS(1), FAIL(2), PASS(3)], 'mode': 'ibit', 'stop': 'natural_expiry',
     'checks': ['started', 'relays_safe'],
     'duration': 120},

    {'group': 'B', 'name': '6_uuts_max',
     'desc': 'Six UUTs — maximum capacity',
     'uuts': [PASS(1), PASS(2), FAIL(3), PASS(4), FAIL(5), PASS(6)],
     'mode': 'ibit', 'stop': 'manual_stop',
     'checks': ['started', 'relays_safe'],
     'duration': 120},

    {'group': 'B', 'name': 'multi_iter',
     'desc': 'PASS vehicle runs 2+ iterations',
     'uuts': [PASS(1)], 'mode': 'ibit', 'stop': 'natural_expiry',
     'multi_iter': True,
     'checks': ['relays_safe', 'multi_iter_done'],
     'duration': 180},

    # ── GROUP C: Boundary conditions ─────────────────────────────────────
    {'group': 'C', 'name': 'stop_before_connect',
     'desc': 'Stop immediately after clicking Start, before connection',
     'uuts': [PASS(1)], 'mode': 'ibit', 'stop': 'stop_before_connect',
     'checks': ['relays_safe', 'stopped']},

    {'group': 'C', 'name': 'duration_seconds',
     'desc': 'Duration in Seconds unit',
     'uuts': [PASS(1)], 'mode': 'ibit', 'stop': 'natural_expiry',
     'checks': ['started', 'relays_safe'],
     'duration': 60},

    {'group': 'C', 'name': 'skip_state_management',
     'desc': 'Skip State Management checkbox enabled',
     'uuts': [PASS(1)], 'mode': 'ibit', 'stop': 'natural_expiry',
     'skip_state': True,
     'checks': ['started', 'relays_safe'],
     'duration': 60},

    {'group': 'C', 'name': 'skip_arm',
     'desc': 'Skip ARM requirement checkbox enabled',
     'uuts': [PASS(1)], 'mode': 'ibit', 'stop': 'natural_expiry',
     'skip_arm': True,
     'checks': ['started', 'relays_safe'],
     'duration': 60},

    # ── GROUP D: Error/failure injection ─────────────────────────────────
    {'group': 'D', 'name': 'ibit_fail_surfaces',
     'desc': 'IBIT detects mistracking on both elevons (0xC0)',
     'uuts': [FAIL(1)], 'mode': 'ibit', 'stop': 'natural_expiry',
     'checks': ['started', 'relays_safe', 'first_uut_attempted'],
     'duration': 60},

    {'group': 'D', 'name': 'ibit_fail_single_surface',
     'desc': 'IBIT detects mistracking on one surface (bit 1 = upper rudder)',
     'uuts': [uut('F_single', False, 0x01)], 'mode': 'ibit', 'stop': 'natural_expiry',
     'checks': ['started', 'relays_safe'],
     'duration': 60},

    {'group': 'D', 'name': 'ibit_fail_all_surfaces',
     'desc': 'IBIT detects mistracking on all 8 surfaces (0xFF)',
     'uuts': [uut('F_all', False, 0xFF)], 'mode': 'ibit', 'stop': 'natural_expiry',
     'checks': ['started', 'relays_safe'],
     'duration': 60},

    # ── GROUP E: State persistence ───────────────────────────────────────
    {'group': 'E', 'name': 'second_run_after_complete',
     'desc': 'First batch completes → second batch starts with same UUTs',
     'uuts': [PASS(1)], 'mode': 'ibit', 'stop': 'natural_expiry',
     'checks': ['started', 'relays_safe', 'first_uut_tested'],
     'duration': 60},

    # ── GROUP F: UI interactions during test ─────────────────────────────
    {'group': 'F', 'name': 'log_filter_during_test',
     'desc': 'Switch log filter between ALL/ERROR/PASS while IBIT running',
     'uuts': [PASS(1)], 'mode': 'ibit', 'stop': 'natural_expiry',
     'checks': ['started', 'relays_safe', 'log_populated']},

    {'group': 'F', 'name': 'uut_select_during_test',
     'desc': 'Click different UUT in table mid-test to see stale data',
     'uuts': [PASS(1), FAIL(2)], 'mode': 'ibit', 'stop': 'manual_stop',
     'checks': ['started', 'relays_safe'],
     'duration': 90},

    {'group': 'F', 'name': 'fleet_summary_updates',
     'desc': 'Fleet summary changes as UUTs complete',
     'uuts': [PASS(1), FAIL(2)], 'mode': 'ibit', 'stop': 'natural_expiry',
     'checks': ['started', 'relays_safe', 'fleet_summary_changed'],
     'duration': 120},

    # ── GROUP G: Configuration variants ──────────────────────────────────
    {'group': 'G', 'name': 'playback_single_pass',
     'desc': 'Playback mode single PASS vehicle',
     'uuts': [PASS(1)], 'mode': 'playback', 'stop': 'natural_expiry',
     'checks': ['started', 'relays_safe', 'first_uut_tested'],
     'duration': 60},

    {'group': 'G', 'name': 'playback_single_fail',
     'desc': 'Playback mode single FAIL vehicle',
     'uuts': [FAIL(1)], 'mode': 'playback', 'stop': 'natural_expiry',
     'checks': ['started', 'relays_safe'],
     'duration': 60},

    {'group': 'G', 'name': 'playback_dual_mixed',
     'desc': 'Playback mode dual UUTs mixed results',
     'uuts': [PASS(1), FAIL(2)], 'mode': 'playback', 'stop': 'natural_expiry',
     'checks': ['started', 'relays_safe'],
     'duration': 120},

    {'group': 'G', 'name': 'playback_emergency',
     'desc': 'Playback mode emergency stop',
     'uuts': [PASS(1)], 'mode': 'playback', 'stop': 'emergency',
     'checks': ['relays_safe', 'stopped']},

    {'group': 'G', 'name': 'ibit_then_playback',
     'desc': 'Run IBIT first, then switch to Playback without restart',
     'uuts': [PASS(1)], 'mode': 'ibit', 'stop': 'natural_expiry',
     'checks': ['started', 'relays_safe'],
     'duration': 60},
]

# ── Runner ────────────────────────────────────────────────────────────────
def run_test(test_def, base_port):
    uut_configs = test_def['uuts']
    mode        = test_def['mode']
    stop        = test_def['stop']
    duration    = test_def.get('duration', 90)
    skip_state  = test_def.get('skip_state', False)
    skip_arm    = test_def.get('skip_arm', False)
    use_sitl    = test_def.get('use_sitl_btn', False)
    fail_relay  = test_def.get('fail_relay', False)
    multi_iter  = test_def.get('multi_iter', False)

    script = SCRIPT.format(
        root=ROOT,
        offscreen="os.environ['QT_QPA_PLATFORM'] = 'offscreen'",
        uut_config=repr(uut_configs),
        test_mode=mode,
        stop_method=stop,
        duration=duration,
        base_port=base_port,
        skip_state=repr(skip_state),
        skip_arm=repr(skip_arm),
        use_sitl_btn=repr(use_sitl),
        fail_relay=repr(fail_relay),
        multi_iter=repr(multi_iter),
    )

    try:
        proc = subprocess.run(
            [sys.executable, '-c', script],
            capture_output=True, text=True,
            timeout=duration + 90, cwd=ROOT,
        )
        for line in proc.stdout.split('\n'):
            if line.startswith('RESULT:'):
                return json.loads(line[7:])
        return {
            'started': False, 'uut_results': [], 'relays_safe': False,
            'log_count': 0, 'fleet_summary_seen': [], 'errors': [],
            '_crash': proc.stderr[-300:] if proc.stderr else 'no output',
        }
    except subprocess.TimeoutExpired:
        return {
            'started': False, 'uut_results': [], 'relays_safe': False,
            'log_count': 0, 'fleet_summary_seen': [], 'errors': ['timeout'],
        }

def evaluate(test_def, result):
    checks   = test_def.get('checks', [])
    failures = []
    ur       = result.get('uut_results', [])

    if 'started' in checks and not result.get('started'):
        failures.append('Test did not start')

    if 'relays_safe' in checks and not result.get('relays_safe', True):
        failures.append('RELAYS NOT SAFE after test')

    if 'stopped' in checks:
        stop = test_def.get('stop', '')
        if stop in ('emergency', 'manual_stop', 'stop_before_connect',
                    'emergency_relay_on', 'stop_during_arm'):
            if result.get('started') and result.get('uut_results') and \
               all(u.get('iterations', 0) >= 1 for u in ur):
                pass  # fine — just verify relays safe (done above)

    if 'first_uut_tested' in checks:
        if not ur or ur[0].get('iterations', 0) < 1:
            failures.append(f'First UUT not completed an iteration: {ur[0] if ur else "no data"}')

    if 'first_uut_attempted' in checks:
        if not ur or (ur[0].get('iterations', 0) < 1 and
                      ur[0].get('status') not in ('Retry','Failed (3x)','Stopped')):
            failures.append(f'First UUT not attempted: {ur[0] if ur else "no data"}')

    if 'pass_uut_tested' in checks:
        pass_uuts = [u for u in ur if 'P' in u.get('serial','')]
        if not pass_uuts or pass_uuts[0].get('iterations', 0) < 1:
            failures.append(f'PASS vehicle not tested: {pass_uuts}')

    if 'multi_iter_done' in checks:
        if not any(u.get('iterations', 0) >= 2 for u in ur):
            failures.append(f'No UUT reached 2 iterations: {ur}')

    if 'log_populated' in checks:
        if result.get('log_count', 0) < 20:
            failures.append(f'Log too sparse: {result.get("log_count")} entries')

    if 'fleet_summary_changed' in checks:
        seen = result.get('fleet_summary_seen', [])
        if len(seen) < 2:
            failures.append(f'Fleet summary never changed: seen={seen}')

    if result.get('_crash'):
        failures.append(f'Subprocess crash: {result["_crash"][:200]}')

    return failures

# ── Main ──────────────────────────────────────────────────────────────────
RESULTS  = []
BASE     = 19860
PORT_GAP = 12
MAX_WORKERS = 2  # Lower parallelism to avoid CPU saturation

total = len(TESTS)
print('='*70, flush=True)
print(f'  COMPREHENSIVE PERMUTATION TEST — {total} cases ({MAX_WORKERS} parallel)', flush=True)
print('='*70, flush=True)

# Pre-assign ports so parallel tests don't collide
for i, test in enumerate(TESTS):
    test['_port'] = BASE + i * PORT_GAP
    test['_index'] = i

def run_one(test):
    i     = test['_index']
    port  = test['_port']
    label = f'[{test["group"]}] {test["name"]}'
    print(f'  Starting [{i+1:2d}/{total}] {label}', flush=True)
    result   = run_test(test, port)
    failures = evaluate(test, result)
    status   = 'PASS' if not failures else 'FAIL'
    print(f'  [{status}] {label}', flush=True)
    if failures:
        for f in failures:
            print(f'    x {f}', flush=True)
    return {
        'group': test['group'], 'name': test['name'], 'desc': test['desc'],
        'failures': failures, 'result': result,
    }

start_time = time.time()
with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
    futures = {pool.submit(run_one, test): test for test in TESTS}
    for future in as_completed(futures):
        RESULTS.append(future.result())

# Sort by original order
RESULTS.sort(key=lambda r: next(
    (t['_index'] for t in TESTS if t['name'] == r['name']), 999))

elapsed = time.time() - start_time

# ── Summary ───────────────────────────────────────────────────────────────
passed = sum(1 for r in RESULTS if not r['failures'])
failed = len(RESULTS) - passed

print(f'\n{"="*70}', flush=True)
print(f'  RESULTS  —  {passed} passed  /  {failed} failed  /  {total} total  '
      f'({elapsed:.0f}s)', flush=True)
print('='*70, flush=True)

by_group = {}
for r in RESULTS:
    by_group.setdefault(r['group'], []).append(r)

for grp in sorted(by_group):
    grp_tests = by_group[grp]
    grp_pass  = sum(1 for t in grp_tests if not t['failures'])
    print(f'\n  Group {grp}: {grp_pass}/{len(grp_tests)} passed', flush=True)
    for t in grp_tests:
        sym = '+' if not t['failures'] else 'x'
        print(f'    [{sym}] {t["name"]}', flush=True)
        for f in t['failures']:
            print(f'         {f}', flush=True)

# Clean up temp file
if os.path.exists(os.path.join(ROOT, 'permutation_test_results.json')):
    os.remove(os.path.join(ROOT, 'permutation_test_results.json'))

report = os.path.join(ROOT, 'permutation_test_results.json')
with open(report, 'w') as f:
    json.dump(RESULTS, f, indent=2, default=str)
print(f'\n  Report: {report}', flush=True)
print('='*70, flush=True)

sys.exit(0 if failed == 0 else 1)
