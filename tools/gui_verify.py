"""
GUI verification test — launches the real GUI on the Windows display,
runs a full IBIT batch with 2 UUTs (1 PASS, 1 FAIL), captures
screenshots at every key moment, and reports what it observed.
"""
import os, sys, time, json, threading
from datetime import datetime

ROOT = r'C:\Anduril\RoadRunner Flight Mode IBIT'
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'vehicle', 'dialects'))
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except:
        pass

# ── Start sim vehicles ──────────────────────────────────────────────────
from sim.vehicle import PandionVehicleSim
from sim.mock_daq import MockDAQController

sim1 = PandionVehicleSim(vehicle_port=19995, sysid=1, ibit_pass=True,
    boot_time_s=1.5, ibit_duration_scale=0.3, boot_monitors=[0, 1, 2, 3])
sim2 = PandionVehicleSim(vehicle_port=19996, sysid=2, ibit_pass=False,
    mistracking_flags=0xC0, boot_time_s=1.5, ibit_duration_scale=0.3,
    boot_monitors=[0, 1, 2, 3])
threading.Thread(target=sim1.start, daemon=True).start()
threading.Thread(target=sim2.start, daemon=True).start()
time.sleep(2)

# ── Patch for sim ────────────────────────────────────────────────────────
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

# ── Patch QMessageBox ────────────────────────────────────────────────────
from PyQt5.QtWidgets import QMessageBox, QApplication
from PyQt5.QtCore import QTimer
QMessageBox.question = lambda *a, **kw: QMessageBox.Yes
QMessageBox.information = lambda *a, **kw: None
QMessageBox.critical = lambda *a, **kw: None

# ── Launch GUI on real display ───────────────────────────────────────────
app = QApplication(sys.argv)
from ui import theme as T
T.apply(app)
from ui.main_window import MultiUUTTestGUI
from vehicle.connection import UUT

win = MultiUUTTestGUI()
win.daq = MockDAQController()
win.daq.initialize('MockDAQ')

uut1 = UUT('RR-PASS-001', '127.0.0.1', 19995, 0)
uut2 = UUT('RR-FAIL-002', '127.0.0.1', 19996, 1)
win.uuts = [uut1, uut2]
win.uut_table_widget.update_table(win.uuts)
win.resize(1600, 900)
win.show()
win.raise_()
win.activateWindow()

# ── Screenshot + observation infrastructure ──────────────────────────────
shot_dir = os.path.join(ROOT, 'screenshots', 'verification')
os.makedirs(shot_dir, exist_ok=True)

observations = []

def observe(name, checks):
    """Capture screenshot + record observations."""
    app.processEvents()
    time.sleep(0.1)
    app.processEvents()

    # Screenshot
    pixmap = win.grab()
    path = os.path.join(shot_dir, f'{name}.png')
    pixmap.save(path, 'PNG')

    # Collect state
    obs = {
        'step': name,
        'time': datetime.now().strftime('%H:%M:%S.%f')[:-3],
        'screenshot': path,
        'screenshot_size': f'{pixmap.width()}x{pixmap.height()}',
    }

    # Run checks
    for check_name, check_fn in checks.items():
        try:
            result = check_fn()
            obs[check_name] = result
        except Exception as e:
            obs[check_name] = f'ERROR: {e}'

    observations.append(obs)
    print(f'  [{name}] {json.dumps({k:v for k,v in obs.items() if k != "screenshot"}, indent=None)}', flush=True)

def get_fleet_summary():
    return win.uut_table_widget._fleet_summary.text()

def get_uut_statuses():
    return [(u.serial_number, u.status, u.iterations_completed) for u in win.uuts]

def get_log_count():
    return len(win.log_widget._all_entries) if hasattr(win.log_widget, '_all_entries') else -1

def get_ibit_display():
    return win.ibit_display._substate_label.text() if hasattr(win.ibit_display, '_substate_label') else '?'

def get_status_panel():
    result = {}
    try: result['connection'] = win.status_panel._connection_led._state
    except: pass
    try: result['armed'] = win.status_panel._armed_led._state
    except: pass
    try: result['mode'] = win.status_panel.mode_badge.text()
    except: result['mode'] = '?'
    return result

def get_actuator_first_fb():
    """Get left elevon feedback value."""
    try:
        return win.actuator_display._rows['left_elevon']['fb'].text()
    except:
        return '?'

def is_testing():
    return win.testing_active

def check_report_exists():
    if os.path.exists(win.report_directory):
        reports = [f for f in os.listdir(win.report_directory) if f.endswith('.json')]
        return len(reports) > 0
    return False

# ── Test sequence via QTimer ─────────────────────────────────────────────
step = [0]
def tick():
    s = step[0]
    step[0] += 1

    try:
        if s == 1:
            observe('01_initial', {
                'fleet_summary': get_fleet_summary,
                'uut_statuses': get_uut_statuses,
                'testing': is_testing,
                'log_count': get_log_count,
                'actuator_fb': get_actuator_first_fb,
            })

        elif s == 3:
            # Start test
            win._auto_start_test(180)
            observe('02_test_started', {
                'testing': is_testing,
                'fleet_summary': get_fleet_summary,
                'uut_statuses': get_uut_statuses,
            })

        elif s == 8:
            observe('03_connecting', {
                'testing': is_testing,
                'fleet_summary': get_fleet_summary,
                'status_panel': get_status_panel,
                'log_count': get_log_count,
            })

        elif s == 15:
            observe('04_arming', {
                'testing': is_testing,
                'status_panel': get_status_panel,
                'ibit_display': get_ibit_display,
                'actuator_fb': get_actuator_first_fb,
            })

        elif s == 25:
            observe('05_ibit_running', {
                'testing': is_testing,
                'status_panel': get_status_panel,
                'ibit_display': get_ibit_display,
                'actuator_fb': get_actuator_first_fb,
                'log_count': get_log_count,
            })

        elif s == 40:
            observe('06_first_uut_done', {
                'testing': is_testing,
                'fleet_summary': get_fleet_summary,
                'uut_statuses': get_uut_statuses,
                'actuator_fb': get_actuator_first_fb,
            })

        elif s == 55:
            observe('07_second_uut_ibit', {
                'testing': is_testing,
                'fleet_summary': get_fleet_summary,
                'status_panel': get_status_panel,
                'ibit_display': get_ibit_display,
                'actuator_fb': get_actuator_first_fb,
            })

        elif s == 75:
            observe('08_second_uut_done', {
                'testing': is_testing,
                'fleet_summary': get_fleet_summary,
                'uut_statuses': get_uut_statuses,
                'log_count': get_log_count,
            })

        elif s == 95:
            observe('09_batch_finishing', {
                'testing': is_testing,
                'fleet_summary': get_fleet_summary,
                'uut_statuses': get_uut_statuses,
                'report_exists': check_report_exists,
                'log_count': get_log_count,
            })

        elif s == 100:
            # Final summary
            print('\n' + '='*60, flush=True)
            print('  VERIFICATION REPORT', flush=True)
            print('='*60, flush=True)
            print(f'  Screenshots: {len(observations)}', flush=True)
            print(f'  Location: {shot_dir}', flush=True)
            print(flush=True)

            all_ok = True
            for obs in observations:
                step_name = obs['step']
                issues = []

                # Check for ERROR values
                for k, v in obs.items():
                    if isinstance(v, str) and v.startswith('ERROR:'):
                        issues.append(f'{k}: {v}')

                if issues:
                    print(f'  [ISSUE] {step_name}: {"; ".join(issues)}', flush=True)
                    all_ok = False
                else:
                    print(f'  [OK] {step_name}', flush=True)

            # Final UUT results
            print(flush=True)
            for u in win.uuts:
                print(f'  UUT {u.serial_number}: status={u.status}, iterations={u.iterations_completed}', flush=True)

            print(flush=True)
            if all_ok:
                print('  VERDICT: ALL CHECKS PASSED', flush=True)
            else:
                print('  VERDICT: ISSUES FOUND', flush=True)
            print('='*60, flush=True)

            # Write report JSON
            report_path = os.path.join(shot_dir, 'verification_report.json')
            with open(report_path, 'w') as f:
                json.dump(observations, f, indent=2, default=str)
            print(f'  Report: {report_path}', flush=True)

            app.quit()

    except Exception as e:
        print(f'  ERROR at step {s}: {e}', flush=True)
        import traceback
        traceback.print_exc()

timer = QTimer()
timer.timeout.connect(tick)
timer.start(1000)
app.exec_()
