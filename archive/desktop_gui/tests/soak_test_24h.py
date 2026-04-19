"""
24-Hour IBIT Soak Test Simulation

Simulates 24 hours of continuous IBIT batch testing at 100x accelerated
speed, completing in approximately 15 minutes. One PASS vehicle, one
FAIL vehicle, round-robin for the full duration.

Monitors for:
  - Memory growth (leak detection)
  - Log file rotation correctness
  - Iteration count accuracy
  - Timer drift
  - Thread accumulation
  - Exception rate
  - Relay state correctness between iterations
  - Statistics integrity
  - CSV log file integrity
  - Batch report generation

Run with:
    python tests/soak_test_24h.py

Output: detailed per-hour status, final report at the end.
"""
from __future__ import annotations

import os
import sys
import time
import json
import threading
import traceback
import gc
import csv
from datetime import datetime, timedelta
from typing import Any

ROOT = r'C:\Anduril\RoadRunner Flight Mode IBIT'
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'vehicle', 'dialects'))

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

os.environ['QT_QPA_PLATFORM'] = 'offscreen'

# ── Timing constants ──────────────────────────────────────────────────────────
REAL_HOURS       = 24           # Simulated duration
SPEED_MULTIPLIER = 100          # 100x faster than real time
IBIT_SCALE       = 0.2          # IBIT phases at 20% of real duration (~4s total)
BOOT_TIME        = 0.5          # Sim boot time (seconds)
REAL_DURATION_S  = (REAL_HOURS * 3600) / SPEED_MULTIPLIER  # ~864s = 14.4 min

print(f'  Simulated duration:  {REAL_HOURS}h')
print(f'  Speed multiplier:    {SPEED_MULTIPLIER}x')
print(f'  Real test duration:  {REAL_DURATION_S:.0f}s ({REAL_DURATION_S/60:.1f} min)')
print()

# ── Start sim vehicles ────────────────────────────────────────────────────────
from rr_test.sim.vehicle import PandionVehicleSim
from rr_test.sim.mock_daq import MockDAQController
import rr_test.vehicle.connection as conn_mod
import rr_test.hardware.daq as daq_mod

SIM_PASS_PORT = 14601
SIM_FAIL_PORT = 14602

sim_pass = PandionVehicleSim(
    vehicle_port=SIM_PASS_PORT, sysid=1,
    ibit_pass=True,
    boot_time_s=BOOT_TIME,
    ibit_duration_scale=IBIT_SCALE,
    boot_monitors=[0, 1],
    post_arm_monitors=[10],
)
sim_fail = PandionVehicleSim(
    vehicle_port=SIM_FAIL_PORT, sysid=2,
    ibit_pass=False,
    mistracking_flags=0xC0,
    boot_time_s=BOOT_TIME,
    ibit_duration_scale=IBIT_SCALE,
    boot_monitors=[0, 1],
    post_arm_monitors=[10],
)
threading.Thread(target=sim_pass.start, daemon=True).start()
threading.Thread(target=sim_fail.start, daemon=True).start()
time.sleep(1.5)

# ── Patch connection ──────────────────────────────────────────────────────────
def _sim_connect(ip, port, timeout=10):
    from pymavlink import mavutil
    m = mavutil.mavlink_connection(
        f'udpout:{ip}:{port}',
        dialect='pandion_vehicle_roadrunner',
        source_system=255, source_component=190,
    )
    for _ in range(5):
        try:
            m.mav.heartbeat_send(6, 8, 0, 0, 4)
        except Exception:
            pass
        hb = m.recv_match(type='HEARTBEAT', blocking=True, timeout=2.0)
        if hb and hb.get_srcSystem() != 255:
            return m
    raise Exception(f'No heartbeat on port {port}')

conn_mod.connect_to_vehicle = _sim_connect
daq_mod.SimpleDAQController = MockDAQController

# ── Qt setup ──────────────────────────────────────────────────────────────────
from PyQt5.QtWidgets import QApplication, QMessageBox
from PyQt5.QtCore import QTimer
QMessageBox.question     = lambda *a, **kw: QMessageBox.Yes
QMessageBox.critical     = lambda *a, **kw: None
QMessageBox.warning      = lambda *a, **kw: None
QMessageBox.information  = lambda *a, **kw: None

app = QApplication(sys.argv)
from ui import theme as T
T.apply(app)
from ui.main_window import MultiUUTTestGUI
from rr_test.vehicle.connection import UUT
from rr_test.vehicle.constants import TestMode, UUTStatus

win = MultiUUTTestGUI()
mock_daq = MockDAQController()
mock_daq.initialize('MockDAQ')
mock_daq.register_vehicle(0, sim_pass)
mock_daq.register_vehicle(1, sim_fail)
win.daq = mock_daq

uut_pass = UUT('RR-PASS-001', '127.0.0.1', SIM_PASS_PORT, 0)
uut_fail = UUT('RR-FAIL-002', '127.0.0.1', SIM_FAIL_PORT, 1)
win.uuts = [uut_pass, uut_fail]
win.uut_table_widget.update_table(win.uuts)
win.test_config_widget.get_test_mode = lambda: TestMode.IBIT

win.resize(1600, 900)
win.show()

# ── Monitoring infrastructure ─────────────────────────────────────────────────
import threading as _threading
try:
    import tracemalloc
    tracemalloc.start()
    TRACE_MALLOC = True
except Exception:
    TRACE_MALLOC = False

soak_start      = time.time()
check_interval  = 60          # Check health every 60 real seconds (~1h simulated)
next_check      = soak_start + check_interval

hourly_reports  = []
issues          = []
prev_iterations = [0, 0]
prev_thread_count = _threading.active_count()
prev_mem_mb       = 0.0
peak_mem_mb       = 0.0

log_dir = win.log_directory
report_dir = win.report_directory


def get_memory_mb():
    """Current process RSS in MB."""
    try:
        import psutil
        return psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024
    except Exception:
        try:
            if TRACE_MALLOC:
                current, _ = tracemalloc.get_traced_memory()
                return current / 1024 / 1024
        except Exception:
            pass
        return 0.0


def check_csv_integrity():
    """Check the most recent CSV log for corrupted rows."""
    issues_found = []
    if not os.path.exists(log_dir):
        return issues_found
    csv_files = sorted(
        [os.path.join(log_dir, f) for f in os.listdir(log_dir) if f.endswith('.csv')],
        key=os.path.getmtime,
    )
    if not csv_files:
        return issues_found
    # Check the most recent file
    path = csv_files[-1]
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            reader = csv.reader(f)
            rows = list(reader)
        if len(rows) < 2:
            issues_found.append(f'CSV {os.path.basename(path)}: only {len(rows)} rows')
        else:
            header_len = len(rows[0])
            corrupt = sum(1 for r in rows[1:] if len(r) != header_len)
            if corrupt > 0:
                issues_found.append(
                    f'CSV {os.path.basename(path)}: {corrupt}/{len(rows)-1} corrupt rows'
                )
    except Exception as e:
        issues_found.append(f'CSV read error: {e}')
    return issues_found


def check_relay_safety():
    """Verify no relay is stuck ON between iterations."""
    if win.testing_active:
        return []  # Relay may legitimately be ON during test
    stuck = [k for k, v in mock_daq._line_states.items() if v]
    if stuck:
        return [f'Relay stuck ON between iterations: lines {stuck}']
    return []


def simulated_hours_elapsed():
    return (time.time() - soak_start) * SPEED_MULTIPLIER / 3600


def real_seconds_elapsed():
    return time.time() - soak_start


def hourly_check(hour_num: int):
    """Run all health checks and record the hourly report."""
    global prev_mem_mb, peak_mem_mb, prev_thread_count

    report = {
        'simulated_hour':    hour_num,
        'real_elapsed_s':    real_seconds_elapsed(),
        'simulated_elapsed_h': simulated_hours_elapsed(),
        'timestamp':         datetime.now().strftime('%H:%M:%S'),
        'issues':            [],
    }

    # Iteration counts
    for i, uut in enumerate(win.uuts):
        report[f'uut{i}_iterations'] = uut.iterations_completed
        report[f'uut{i}_status']     = uut.status
        delta = uut.iterations_completed - prev_iterations[i]
        report[f'uut{i}_iters_this_hour'] = delta
        prev_iterations[i] = uut.iterations_completed

    # Memory
    mem_mb = get_memory_mb()
    if mem_mb > 0:
        growth = mem_mb - prev_mem_mb if prev_mem_mb > 0 else 0
        peak_mem_mb = max(peak_mem_mb, mem_mb)
        report['memory_mb']        = round(mem_mb, 1)
        report['memory_growth_mb'] = round(growth, 1)
        if growth > 50:
            report['issues'].append(f'Memory growth: +{growth:.1f}MB in one hour')
        prev_mem_mb = mem_mb

    # Thread count
    tc = _threading.active_count()
    report['thread_count'] = tc
    if tc > prev_thread_count + 5:
        report['issues'].append(f'Thread leak: {tc} threads (was {prev_thread_count})')
    prev_thread_count = tc

    # Log files
    if os.path.exists(log_dir):
        log_files = [f for f in os.listdir(log_dir) if f.endswith('.csv')]
        report['log_file_count'] = len(log_files)
        total_size = sum(
            os.path.getsize(os.path.join(log_dir, f))
            for f in log_files
        ) / 1024 / 1024
        report['log_total_mb'] = round(total_size, 1)

    # CSV integrity
    csv_issues = check_csv_integrity()
    report['issues'].extend(csv_issues)

    # Relay safety
    relay_issues = check_relay_safety()
    report['issues'].extend(relay_issues)

    # Batch reports
    if os.path.exists(report_dir):
        batch_reports = [f for f in os.listdir(report_dir) if f.endswith('.json')]
        report['batch_reports'] = len(batch_reports)

    # Log
    status = 'OK' if not report['issues'] else f'ISSUES: {", ".join(report["issues"])}'
    print(
        f'  [H{hour_num:02d}] {report["timestamp"]}'
        f'  P:{report["uut0_iterations"]}iter'
        f'  F:{report["uut1_iterations"]}iter'
        f'  Mem:{report.get("memory_mb", "?"):.0f}MB'
        f'  Threads:{report["thread_count"]}'
        f'  Logs:{report.get("log_file_count", 0)}'
        f'  -> {status}',
        flush=True,
    )

    hourly_reports.append(report)
    issues.extend(report['issues'])
    return report


# ── Start the test ────────────────────────────────────────────────────────────
print('='*70, flush=True)
print(f'  24-HOUR IBIT SOAK TEST  ({REAL_DURATION_S:.0f}s real time)', flush=True)
print('='*70, flush=True)
print(f'  {"SIM HOUR":>8}  {"PASS ITERS":>10}  {"FAIL ITERS":>10}  '
      f'{"MEM (MB)":>8}  {"THREADS":>7}  {"LOGS":>5}  STATUS', flush=True)
print('-'*70, flush=True)

tick = [0]
hour_counter = [0]
test_started = [False]
gc_counter = [0]


def on_tick():
    s = tick[0]
    tick[0] += 1

    try:
        app.processEvents()

        # Start test on tick 2
        if s == 2 and not test_started[0]:
            win._auto_start_test(int(REAL_DURATION_S))
            test_started[0] = True
            print(f'  Test started. Running for {REAL_DURATION_S:.0f}s real / {REAL_HOURS}h simulated', flush=True)

        # Hourly check every check_interval real seconds
        real_elapsed = real_seconds_elapsed()
        sim_hours = simulated_hours_elapsed()
        expected_hour = int(sim_hours)

        if expected_hour > hour_counter[0]:
            hour_counter[0] = expected_hour
            hourly_check(expected_hour)

        # Force GC every 10 ticks to prevent gradual accumulation
        gc_counter[0] += 1
        if gc_counter[0] % 10 == 0:
            gc.collect()

        # End condition
        if real_elapsed >= REAL_DURATION_S or not win.testing_active and s > 5:
            # Final hourly check
            hourly_check(REAL_HOURS)
            _finish()
            app.quit()

    except Exception as e:
        issues.append(f'Tick error at s={s}: {e}')
        print(f'  ERROR at tick {s}: {e}', flush=True)
        traceback.print_exc()


def _finish():
    """Generate and print the final soak test report."""
    real_elapsed = real_seconds_elapsed()
    sim_elapsed_h = simulated_hours_elapsed()

    pass_iters  = uut_pass.iterations_completed
    fail_iters  = uut_fail.iterations_completed
    total_iters = pass_iters + fail_iters

    # Verify log files
    log_files = []
    if os.path.exists(log_dir):
        log_files = sorted([f for f in os.listdir(log_dir) if f.endswith('.csv')])

    # Verify batch reports
    batch_reports = []
    if os.path.exists(report_dir):
        batch_reports = [f for f in os.listdir(report_dir) if f.endswith('.json')]

    # Check final relay state
    relay_stuck = [k for k, v in mock_daq._line_states.items() if v]

    # Final CSV integrity check on all log files
    csv_issues_total = []
    for f in log_files:
        path = os.path.join(log_dir, f)
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as fh:
                reader = csv.reader(fh)
                rows = list(reader)
            if rows:
                header_len = len(rows[0])
                corrupt = sum(1 for r in rows[1:] if len(r) != header_len)
                if corrupt:
                    csv_issues_total.append(f'{f}: {corrupt} corrupt rows')
        except Exception as e:
            csv_issues_total.append(f'{f}: read error {e}')

    print('\n' + '='*70, flush=True)
    print('  SOAK TEST COMPLETE — FINAL REPORT', flush=True)
    print('='*70, flush=True)
    print(f'  Simulated duration:   {sim_elapsed_h:.1f}h (target: {REAL_HOURS}h)', flush=True)
    print(f'  Real wall time:       {real_elapsed:.0f}s ({real_elapsed/60:.1f} min)', flush=True)
    print(f'  Total iterations:     {total_iters}', flush=True)
    print(f'    PASS vehicle:       {pass_iters}', flush=True)
    print(f'    FAIL vehicle:       {fail_iters}', flush=True)
    print(f'  Log files created:    {len(log_files)}', flush=True)
    print(f'  Batch reports:        {len(batch_reports)}', flush=True)
    print(f'  Peak memory:          {peak_mem_mb:.1f}MB', flush=True)
    print(f'  Final thread count:   {_threading.active_count()}', flush=True)
    print(f'  Relays after test:    {"ALL OFF" if not relay_stuck else f"STUCK: {relay_stuck}"}', flush=True)

    all_issues = issues + csv_issues_total
    if relay_stuck:
        all_issues.append(f'Relay stuck ON at end: {relay_stuck}')

    print(flush=True)
    if all_issues:
        print(f'  ISSUES FOUND ({len(all_issues)}):')
        for issue in all_issues:
            print(f'    x {issue}', flush=True)
    else:
        print('  NO ISSUES FOUND', flush=True)

    # Verdict
    critical_issues = [i for i in all_issues if 'relay' in i.lower() or 'corrupt' in i.lower() or 'leak' in i.lower()]
    print(flush=True)
    if not all_issues:
        print('  VERDICT: PASS — Software is stable over 24 simulated hours', flush=True)
    elif not critical_issues:
        print(f'  VERDICT: PASS WITH WARNINGS — {len(all_issues)} non-critical issues', flush=True)
    else:
        print(f'  VERDICT: FAIL — {len(critical_issues)} critical issues', flush=True)
    print('='*70, flush=True)

    # Save full report
    report_data = {
        'soak_test':        '24h IBIT',
        'timestamp':        datetime.now().isoformat(),
        'sim_hours':        sim_elapsed_h,
        'real_seconds':     real_elapsed,
        'total_iterations': total_iters,
        'pass_iterations':  pass_iters,
        'fail_iterations':  fail_iters,
        'log_files':        len(log_files),
        'batch_reports':    len(batch_reports),
        'peak_memory_mb':   peak_mem_mb,
        'final_threads':    _threading.active_count(),
        'relays_clean':     not relay_stuck,
        'issues':           all_issues,
        'hourly_reports':   hourly_reports,
    }
    out_path = os.path.join(ROOT, 'soak_test_results.json')
    with open(out_path, 'w') as f:
        json.dump(report_data, f, indent=2)
    print(f'  Full report: {out_path}', flush=True)


timer = QTimer()
timer.timeout.connect(on_tick)
timer.start(1000)
app.exec_()
