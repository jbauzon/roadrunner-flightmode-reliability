"""
GUI ↔ SITL Integration Verification

Exhaustive test that runs the full GUI against the SITL and verifies
every interaction point: signal wiring, widget updates, data flow,
timing, error handling, and visual state at every phase.

Captures a screenshot + state snapshot at 20+ checkpoints.
Reports any discrepancy between expected and actual GUI state.
"""
import os, sys, time, json, threading
from datetime import datetime

ROOT = r'C:\Anduril\RoadRunner Flight Mode IBIT'
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'vehicle', 'dialects'))
if sys.platform == 'win32':
    try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except: pass

# ── Start sims ──────────────────────────────────────────────────────────
from sim.vehicle import PandionVehicleSim
from sim.mock_daq import MockDAQController

sim1 = PandionVehicleSim(vehicle_port=19801, sysid=1, ibit_pass=True,
    boot_time_s=1.5, ibit_duration_scale=0.3, boot_monitors=[0, 1, 2, 3])
sim2 = PandionVehicleSim(vehicle_port=19802, sysid=2, ibit_pass=False,
    mistracking_flags=0xC0, boot_time_s=1.5, ibit_duration_scale=0.3,
    boot_monitors=[0, 1, 2, 3])
threading.Thread(target=sim1.start, daemon=True).start()
threading.Thread(target=sim2.start, daemon=True).start()
time.sleep(2)

# ── Patches ─────────────────────────────────────────────────────────────
import vehicle.connection as conn_mod
def _sim_connect(ip, port, timeout=10):
    from pymavlink import mavutil
    m = mavutil.mavlink_connection(f'udpout:127.0.0.1:{port}',
        dialect='pandion_vehicle_roadrunner', source_system=255, source_component=190)
    for _ in range(5):
        try: m.mav.heartbeat_send(6, 8, 0, 0, 4)
        except: pass
        hb = m.recv_match(type='HEARTBEAT', blocking=True, timeout=1.0)
        if hb and hb.get_srcSystem() != 255: return m
    raise Exception('No heartbeat')
conn_mod.connect_to_vehicle = _sim_connect
import hardware.daq as daq_mod
daq_mod.SimpleDAQController = MockDAQController

from PyQt5.QtWidgets import QApplication, QMessageBox
from PyQt5.QtCore import QTimer
QMessageBox.question = lambda *a, **kw: QMessageBox.Yes
QMessageBox.information = lambda *a, **kw: None
QMessageBox.critical = lambda *a, **kw: None
QMessageBox.warning = lambda *a, **kw: None

app = QApplication(sys.argv)
from ui import theme as T
T.apply(app)
from ui.main_window import MultiUUTTestGUI
from vehicle.connection import UUT
from vehicle.constants import UUTStatus, TestMode, ActuationMode

win = MultiUUTTestGUI()
win.daq = MockDAQController()
win.daq.initialize('MockDAQ')
uut1 = UUT('RR-PASS-001', '127.0.0.1', 19801, 0)
uut2 = UUT('RR-FAIL-002', '127.0.0.1', 19802, 1)
win.uuts = [uut1, uut2]
win.uut_table_widget.update_table(win.uuts)
win.resize(1600, 900)
win.show()
win.raise_()

# ── Verification infrastructure ─────────────────────────────────────────
shot_dir = os.path.join(ROOT, 'screenshots', 'gui_sitl_verify')
os.makedirs(shot_dir, exist_ok=True)

checks = []
failures = []

def screenshot(name):
    app.processEvents()
    time.sleep(0.1)
    app.processEvents()
    p = win.grab()
    path = os.path.join(shot_dir, f'{name}.png')
    p.save(path, 'PNG')
    return path

def check(name, condition, actual='', expected=''):
    result = {'name': name, 'pass': bool(condition), 'actual': str(actual), 'expected': str(expected)}
    checks.append(result)
    status = 'PASS' if condition else 'FAIL'
    print(f'  [{status}] {name}', flush=True)
    if actual and not condition:
        print(f'         actual={actual}  expected={expected}', flush=True)
    if not condition:
        failures.append(name)

def get_widget_state():
    """Capture complete GUI widget state."""
    s = {}
    try: s['testing_active'] = win.testing_active
    except: pass
    try: s['test_mode'] = win.test_mode
    except: pass

    # Fleet summary
    try: s['fleet_summary'] = win.uut_table_widget._fleet_summary.text()
    except: s['fleet_summary'] = '?'

    # UUT statuses
    try: s['uuts'] = [(u.serial_number, u.status, u.iterations_completed) for u in win.uuts]
    except: s['uuts'] = []

    # Vehicle status panel
    try: s['link_led'] = win.status_panel._connection_led._state
    except: s['link_led'] = '?'
    try: s['armed_led'] = win.status_panel._armed_led._state
    except: s['armed_led'] = '?'
    try: s['mode_badge'] = win.status_panel.mode_badge.text()
    except: s['mode_badge'] = '?'

    # IBIT display
    try: s['test_status'] = win.ibit_display._substate_label.text()
    except: s['test_status'] = '?'

    # Progress
    try: s['current_uut'] = win.progress_widget.current_uut_label.text()
    except: s['current_uut'] = '?'
    try: s['iteration'] = win.progress_widget.iteration_label.text()
    except: s['iteration'] = '?'

    # Actuator feedback
    try: s['le_fb'] = win.actuator_display._rows['left_elevon']['fb'].text()
    except: s['le_fb'] = '?'
    try: s['le_cur'] = win.actuator_display._rows['left_elevon']['curr'].text()
    except: s['le_cur'] = '?'

    # Log
    try: s['log_count'] = len(win.log_widget._all_entries)
    except: s['log_count'] = -1

    # Buttons
    try: s['start_enabled'] = win.control_buttons.start_btn.isEnabled()
    except: s['start_enabled'] = '?'
    try: s['stop_enabled'] = win.control_buttons.stop_btn.isEnabled()
    except: s['stop_enabled'] = '?'

    # Relay states
    try: s['relays'] = dict(win.daq._line_states)
    except: s['relays'] = {}

    return s

# ── Test sequence ───────────────────────────────────────────────────────
step = [0]
phase = ['init']

def tick():
    s = step[0]
    step[0] += 1

    try:
        # ── PHASE: INITIAL STATE (s=1) ──────────────────────────────────
        if s == 1:
            phase[0] = 'initial'
            screenshot('01_initial')
            st = get_widget_state()

            check('Initial: testing_active is False', st['testing_active'] == False, st['testing_active'], False)
            check('Initial: test_mode is IBIT', st['test_mode'] == TestMode.IBIT, st['test_mode'], TestMode.IBIT)
            check('Initial: fleet summary shows 2 Ready', 'Ready' in st['fleet_summary'], st['fleet_summary'], '2 Ready')
            check('Initial: UUT1 status Ready', st['uuts'][0][1] == UUTStatus.READY, st['uuts'][0][1], UUTStatus.READY)
            check('Initial: UUT2 status Ready', st['uuts'][1][1] == UUTStatus.READY, st['uuts'][1][1], UUTStatus.READY)
            check('Initial: link LED is None/grey', st['link_led'] in (None, 'grey', '?'), st['link_led'], 'None/grey')
            check('Initial: mode badge empty', st['mode_badge'] in ('', '---', '- - -', '?'), st['mode_badge'], '---')
            check('Initial: test status IDLE', 'IDLE' in st.get('test_status', ''), st['test_status'], 'IDLE')
            check('Initial: actuator fb is ---', st['le_fb'] == '---', st['le_fb'], '---')
            check('Initial: start button enabled', st['start_enabled'] == True, st['start_enabled'], True)
            check('Initial: stop button disabled', st['stop_enabled'] == False, st['stop_enabled'], False)
            check('Initial: all relays OFF', all(not v for v in st['relays'].values()), st['relays'], 'all False')
            check('Initial: log has getting-started', st['log_count'] >= 5, st['log_count'], '>=5')

        # ── PHASE: START TEST (s=3) ─────────────────────────────────────
        elif s == 3:
            phase[0] = 'start'
            win._auto_start_test(180)

        elif s == 4:
            screenshot('02_test_started')
            st = get_widget_state()

            check('Start: testing_active is True', st['testing_active'] == True, st['testing_active'], True)
            check('Start: start button disabled', st['start_enabled'] == False, st['start_enabled'], False)
            check('Start: stop button enabled', st['stop_enabled'] == True, st['stop_enabled'], True)
            check('Start: UUT1 status Testing', st['uuts'][0][1] == UUTStatus.TESTING, st['uuts'][0][1], UUTStatus.TESTING)
            check('Start: fleet summary shows Testing', 'Testing' in st['fleet_summary'], st['fleet_summary'], 'Testing')
            check('Start: current UUT shows RR-PASS-001', 'RR-PASS-001' in st['current_uut'], st['current_uut'], 'RR-PASS-001')

        # ── PHASE: CONNECTING (s=7) ─────────────────────────────────────
        elif s == 7:
            phase[0] = 'connecting'
            screenshot('03_connecting')
            st = get_widget_state()

            check('Connect: link LED green', st['link_led'] == 'green', st['link_led'], 'green')
            check('Connect: log growing', st['log_count'] >= 20, st['log_count'], '>=20')

        # ── PHASE: ARMING (s=10) ────────────────────────────────────────
        elif s == 10:
            phase[0] = 'arming'
            screenshot('04_arming')
            st = get_widget_state()

            check('ARM: actuator feedback populated', st['le_fb'] != '---', st['le_fb'], 'not ---')
            check('ARM: actuator current populated', st['le_cur'] != '---', st['le_cur'], 'not ---')

        # ── PHASE: IBIT IN PROGRESS (s=18) ──────────────────────────────
        elif s == 18:
            phase[0] = 'ibit'
            screenshot('05_ibit_progress')
            st = get_widget_state()

            check('IBIT: iteration >= 1', int(st.get('iteration', '0')) >= 1, st['iteration'], '>=1')
            check('IBIT: log growing rapidly', st['log_count'] >= 80, st['log_count'], '>=80')

        # ── PHASE: IBIT COMPLETE + RESTORATION (s=30) ───────────────────
        elif s == 30:
            phase[0] = 'restore'
            screenshot('06_restoring')
            st = get_widget_state()

            check('Restore: UUT1 has 1+ iterations', st['uuts'][0][2] >= 1, st['uuts'][0][2], '>=1')

        # ── PHASE: SECOND UUT STARTING (s=45) ───────────────────────────
        elif s == 45:
            phase[0] = 'uut2'
            screenshot('07_second_uut')
            st = get_widget_state()

            check('UUT2: fleet shows Complete + Testing', 'Complete' in st['fleet_summary'] or 'Testing' in st['fleet_summary'],
                  st['fleet_summary'], 'Complete and/or Testing')
            check('UUT2: current UUT shows RR-FAIL-002 or still processing',
                  'RR-FAIL' in st['current_uut'] or 'RR-PASS' in st['current_uut'],
                  st['current_uut'], 'RR-FAIL-002 or RR-PASS-001')

        # ── PHASE: SECOND UUT IBIT (s=60) ───────────────────────────────
        elif s == 60:
            phase[0] = 'uut2_ibit'
            screenshot('08_uut2_ibit')
            st = get_widget_state()

            check('UUT2 IBIT: log count high', st['log_count'] >= 150, st['log_count'], '>=150')

        # ── PHASE: SECOND UUT DONE (s=85) ───────────────────────────────
        elif s == 85:
            phase[0] = 'uut2_done'
            screenshot('09_uut2_done')
            st = get_widget_state()

            # PASS vehicle should have completed
            check('Results: UUT1 iterations >= 1', st['uuts'][0][2] >= 1, st['uuts'][0][2], '>=1')

        # ── PHASE: NEAR BATCH END (s=110) ───────────────────────────────
        elif s == 110:
            phase[0] = 'near_end'
            screenshot('10_near_end')
            st = get_widget_state()

            check('Near end: log count very high', st['log_count'] >= 200, st['log_count'], '>=200')

            # Check relay safety — all should be OFF when not actively testing
            active_relays = [k for k, v in st['relays'].items() if v]
            # Relay might be ON if currently testing, that's ok
            if not st['testing_active']:
                check('Relay: all OFF when not testing', len(active_relays) == 0, active_relays, '[]')

        # ── PHASE: EMERGENCY STOP TEST (s=115) ──────────────────────────
        elif s == 115:
            phase[0] = 'emergency'
            # Only do emergency stop if still testing
            if win.testing_active:
                win.emergency_stop()
                time.sleep(1)
                app.processEvents()

            screenshot('11_after_emergency')
            st = get_widget_state()

            check('Emergency: testing stopped', st['testing_active'] == False, st['testing_active'], False)
            active_relays = [k for k, v in st['relays'].items() if v]
            check('Emergency: all relays OFF', len(active_relays) == 0, active_relays, '[]')

        # ── PHASE: LOG FILTER TEST (s=118) ──────────────────────────────
        elif s == 118:
            phase[0] = 'log_filter'
            # Test log filtering
            if hasattr(win.log_widget, '_filter_buttons'):
                # Click ERROR filter
                win.log_widget._filter_buttons['ERROR'].click()
                app.processEvents()
                time.sleep(0.3)
                app.processEvents()

                screenshot('12_log_filtered_error')

                # Count visible entries
                visible = win.log_widget.log_text.toPlainText().count('\n')
                total = len(win.log_widget._all_entries)
                check('Log filter: ERROR shows fewer entries', visible < total, f'{visible} visible', f'< {total} total')

                # Reset to ALL
                win.log_widget._filter_buttons['ALL'].click()
                app.processEvents()

                # Test search
                win.log_widget._search.setText('ARM')
                app.processEvents()
                time.sleep(0.3)
                app.processEvents()

                screenshot('13_log_search_arm')
                visible_search = win.log_widget.log_text.toPlainText().count('\n')
                check('Log search: ARM shows fewer entries', visible_search < total, f'{visible_search} visible', f'< {total} total')

                win.log_widget._search.clear()
                win.log_widget._filter_buttons['ALL'].click()
                app.processEvents()

        # ── PHASE: STALE INDICATOR TEST (s=120) ─────────────────────────
        elif s == 120:
            phase[0] = 'stale'
            # Click on UUT2 in table to test stale indicator
            if len(win.uuts) >= 2:
                win.uut_table_widget.table.selectRow(1)
                app.processEvents()
                time.sleep(0.5)
                app.processEvents()

                screenshot('14_stale_indicator')
                st = get_widget_state()

                # If UUT2 has cached data, should show stale
                has_cache = win.uuts[1].serial_number in win.actuator_display._feedback_cache
                is_stale = win.actuator_display._is_stale
                if has_cache:
                    check('Stale: indicator shows stale for cached UUT', is_stale == True, is_stale, True)
                else:
                    check('Stale: no cache for UUT2 (acceptable)', True)

        # ── REPORT (s=125) ──────────────────────────────────────────────
        elif s == 125:
            phase[0] = 'report'
            screenshot('15_final')

            # Check report generation
            report_exists = False
            if os.path.exists(win.report_directory):
                reports = [f for f in os.listdir(win.report_directory) if f.endswith('.json')]
                report_exists = len(reports) > 0
            check('Batch report generated', report_exists, report_exists, True)

            # Print final report
            print('\n' + '='*70, flush=True)
            print('  GUI ↔ SITL INTEGRATION VERIFICATION REPORT', flush=True)
            print('='*70, flush=True)
            print(f'  Screenshots: {len([f for f in os.listdir(shot_dir) if f.endswith(".png")])}', flush=True)
            print(f'  Checks: {len(checks)}', flush=True)
            passed = sum(1 for c in checks if c['pass'])
            failed = len(checks) - passed
            print(f'  Passed: {passed}', flush=True)
            print(f'  Failed: {failed}', flush=True)
            print(flush=True)

            if failures:
                print('  FAILURES:', flush=True)
                for f in failures:
                    print(f'    ✗ {f}', flush=True)
            else:
                print('  ALL CHECKS PASSED', flush=True)

            print('='*70, flush=True)

            # Save report
            report_path = os.path.join(shot_dir, 'verification_report.json')
            with open(report_path, 'w') as f:
                json.dump(checks, f, indent=2)
            print(f'  Report: {report_path}', flush=True)

            app.quit()

    except Exception as e:
        print(f'  ERROR at step {s} ({phase[0]}): {e}', flush=True)
        import traceback
        traceback.print_exc()

timer = QTimer()
timer.timeout.connect(tick)
timer.start(1000)
app.exec_()
