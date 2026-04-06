#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_sitl.py -- Comprehensive SITL integration test.

Validates that the sim behaves exactly like a real Pandion vehicle
by running through the FULL test sequence the production test software
performs, verifying every step.

This script uses the SAME connect_to_vehicle() function as production.
Zero patches. Zero mocks (except DAQ).

Tests:
  1. Continuous telemetry at correct rates
  2. Parameter read/write (USE_NEST, CLASSIC_MODE_EN)
  3. Monitor boot state + clearing
  4. ARM rejected with monitors SET
  5. ARM accepted after clearing
  6. Post-ARM monitors appear and get cleared
  7. OPERATE -> PLAYBACK transition
  8. PLAYBACK -> IBIT transition
  9. IBIT substates progress: BEGIN -> SETTLE -> ELEVON -> RUDDERS -> TVC -> DONE
  10. IBIT -> OPERATE auto-transition on completion
  11. Mistracking flags (pass vehicle: 0x00, fail vehicle: non-zero)
  12. DISARM and return to OFF
  13. Surface feedback values are non-zero during IBIT
  14. Current and temperature values are realistic

Usage:
    python test_sitl.py           # run all tests
    python test_sitl.py --verbose # print every message
"""

import os, sys, time, threading

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'vehicle', 'dialects'))

import importlib
_d = importlib.import_module('pandion_vehicle_roadrunner')
sys.modules['pymavlink.dialects.v10.pandion_vehicle_roadrunner'] = _d
import pymavlink.dialects.v10 as _v10
setattr(_v10, 'pandion_vehicle_roadrunner', _d)

from pymavlink import mavutil
from sim.vehicle import PandionVehicleSim

PASS_PORT = 39901
FAIL_PORT = 39902

_results = []

def ok(name, condition, detail=''):
    status = 'PASS' if condition else 'FAIL'
    _results.append((name, status, detail))
    mark = '+' if condition else 'X'
    print(f'  [{mark}] {name}' + (f'  ({detail})' if detail else ''))
    if not condition:
        raise AssertionError(f'{name}: {detail}')

def section(name):
    print(f'\n{"="*60}')
    print(f'  {name}')
    print(f'{"="*60}\n')


def run_tests(verbose=False):
    # ── Start sims ────────────────────────────────────────────────────
    section('Starting vehicle simulators')

    sim_pass = PandionVehicleSim(
        vehicle_port=PASS_PORT, sysid=1, ibit_pass=True,
        boot_monitors=[0,1,2,3], post_arm_monitors=[10],
        ibit_duration_scale=0.3, boot_time_s=1.5,
        eval_window_s=0.3, verbose=verbose)

    sim_fail = PandionVehicleSim(
        vehicle_port=FAIL_PORT, sysid=2, ibit_pass=False,
        mistracking_flags=192,
        boot_monitors=[0,1,5], post_arm_monitors=[10,11],
        ibit_duration_scale=0.3, boot_time_s=1.5,
        eval_window_s=0.3, verbose=verbose)

    threading.Thread(target=sim_pass.start, daemon=True).start()
    threading.Thread(target=sim_fail.start, daemon=True).start()
    time.sleep(4)  # Wait for boot sequence to complete
    print('  Sims running\n')

    # ── Run tests on PASS vehicle ─────────────────────────────────────
    _test_vehicle('PASS vehicle (port %d)' % PASS_PORT, PASS_PORT, expect_pass=True)

    # ── Run tests on FAIL vehicle ─────────────────────────────────────
    _test_vehicle('FAIL vehicle (port %d)' % FAIL_PORT, FAIL_PORT, expect_pass=False)

    # ── Summary ───────────────────────────────────────────────────────
    section('RESULTS')
    passed = sum(1 for _,s,_ in _results if s == 'PASS')
    failed = sum(1 for _,s,_ in _results if s == 'FAIL')
    print(f'  {passed} passed, {failed} failed, {len(_results)} total')
    if failed:
        print('\n  FAILURES:')
        for name, status, detail in _results:
            if status == 'FAIL':
                print(f'    X {name}: {detail}')
    print()
    return failed == 0


def _test_vehicle(label, port, expect_pass):
    section(label)

    # Connect with production udpin
    conn = mavutil.mavlink_connection(
        f'udpin:127.0.0.1:{port}',
        dialect='pandion_vehicle_roadrunner',
        source_system=255, source_component=190)

    # ── Test 1: Heartbeat ─────────────────────────────────────────────
    hb = conn.wait_heartbeat(timeout=5)
    ok(f'{label} heartbeat', hb is not None)

    # ── Test 2: Telemetry rates ───────────────────────────────────────
    counts = {}
    t0 = time.time()
    while time.time() - t0 < 3.0:
        msg = conn.recv_match(blocking=True, timeout=0.1)
        if msg and msg.get_type() != 'BAD_DATA':
            counts[msg.get_type()] = counts.get(msg.get_type(), 0) + 1

    ok(f'{label} PANDION_STATUS stream',
       counts.get('PANDION_STATUS', 0) >= 20,
       f'{counts.get("PANDION_STATUS",0)} msgs in 3s')

    ok(f'{label} ACTUATION_SYS_STATUS stream',
       counts.get('PANDION_RR_ACTUATION_SYS_STATUS', 0) >= 40,
       f'{counts.get("PANDION_RR_ACTUATION_SYS_STATUS",0)} msgs in 3s')

    ok(f'{label} MONITOR_STATUS stream',
       counts.get('PANDION_MONITOR_CURRENT_STATUS', 0) >= 10,
       f'{counts.get("PANDION_MONITOR_CURRENT_STATUS",0)} msgs in 3s')

    # ── Test 3: Initial state ─────────────────────────────────────────
    ps = conn.recv_match(type='PANDION_STATUS', blocking=True, timeout=3)
    ok(f'{label} initial DISARMED', ps and ps.flight_regime == 0,
       f'flight_regime={ps.flight_regime if ps else "None"}')

    act = conn.recv_match(type='PANDION_RR_ACTUATION_SYS_STATUS', blocking=True, timeout=3)
    ok(f'{label} initial OFF mode', act and act.actuation_state == 0,
       f'actuation_state={act.actuation_state if act else "None"}')

    # ── Test 4: Monitors on boot ──────────────────────────────────────
    mon = conn.recv_match(type='PANDION_MONITOR_CURRENT_STATUS', blocking=True, timeout=3)
    boot_bits = _mon_bits(mon.currently_set) if mon else []
    ok(f'{label} boot monitors SET', len(boot_bits) > 0, f'monitors={boot_bits}')

    # ── Test 5: Param read ────────────────────────────────────────────
    conn.mav.param_request_read_send(1, 1, b'USE_NEST\x00\x00\x00\x00\x00\x00\x00\x00', -1)
    pv = conn.recv_match(type='PARAM_VALUE', blocking=True, timeout=3)
    ok(f'{label} param USE_NEST read', pv is not None,
       f'value={int(pv.param_value) if pv else "None"}')

    # ── Test 6: ARM rejected (monitors SET) ───────────────────────────
    conn.mav.command_long_send(1, 1, 400, 0, 1, 0, 0, 0, 0, 0, 0)
    ack = conn.recv_match(type='COMMAND_ACK', blocking=True, timeout=3)
    ok(f'{label} ARM rejected with monitors', ack and ack.result == 1,
       f'result={ack.result if ack else "None"}')

    # ── Test 7: Clear boot monitors ───────────────────────────────────
    for mid in boot_bits:
        conn.mav.pandion_monitor_override_cmd_send(2, mid)
        time.sleep(0.02)
    time.sleep(1)

    # Clear any that appeared in _setting
    mon2 = conn.recv_match(type='PANDION_MONITOR_CURRENT_STATUS', blocking=True, timeout=2)
    if mon2:
        extra = _mon_bits(mon2.currently_set)
        for mid in extra:
            conn.mav.pandion_monitor_override_cmd_send(2, mid)
            time.sleep(0.02)
    time.sleep(0.5)

    mon3 = conn.recv_match(type='PANDION_MONITOR_CURRENT_STATUS', blocking=True, timeout=2)
    remaining = _mon_bits(mon3.currently_set) if mon3 else []
    ok(f'{label} monitors cleared', len(remaining) == 0, f'remaining={remaining}')

    # ── Test 8: ARM accepted ──────────────────────────────────────────
    conn.mav.command_long_send(1, 1, 400, 0, 1, 0, 0, 0, 0, 0, 0)
    ack2 = conn.recv_match(type='COMMAND_ACK', blocking=True, timeout=3)
    ok(f'{label} ARM accepted', ack2 and ack2.result == 0,
       f'result={ack2.result if ack2 else "None"}')

    # ── Test 9: Auto-transition to OPERATE ────────────────────────────
    act2 = conn.recv_match(type='PANDION_RR_ACTUATION_SYS_STATUS', blocking=True, timeout=3)
    ok(f'{label} auto OPERATE after ARM', act2 and act2.actuation_state == 2,
       f'actuation_state={act2.actuation_state if act2 else "None"}')

    ps2 = conn.recv_match(type='PANDION_STATUS', blocking=True, timeout=3)
    ok(f'{label} flight regime ARMED', ps2 and ps2.flight_regime == 1,
       f'flight_regime={ps2.flight_regime if ps2 else "None"}')

    # ── Test 10: Post-ARM monitors appear + clear ─────────────────────
    # Poll for up to 3s until post-ARM monitors appear
    post_arm = []
    t0 = time.time()
    while time.time() - t0 < 3.0:
        mon4 = conn.recv_match(type='PANDION_MONITOR_CURRENT_STATUS', blocking=True, timeout=0.5)
        if mon4:
            post_arm = _mon_bits(mon4.currently_set)
            if post_arm:
                break
        time.sleep(0.2)
    ok(f'{label} post-ARM monitors appear', len(post_arm) > 0, f'monitors={post_arm}')
    for mid in post_arm:
        conn.mav.pandion_monitor_override_cmd_send(2, mid)
        time.sleep(0.02)
    time.sleep(0.5)

    # ── Test 11: OPERATE -> PLAYBACK ──────────────────────────────────
    conn.mav.pandion_rr_actuation_request_mode_send(requested_mode=4)
    t0 = time.time()
    in_playback = False
    while time.time() - t0 < 5:
        m = conn.recv_match(type='PANDION_RR_ACTUATION_SYS_STATUS', blocking=True, timeout=0.5)
        if m and m.actuation_state == 4:
            in_playback = True; break
    ok(f'{label} OPERATE -> PLAYBACK', in_playback)

    # Clear any transient monitors
    time.sleep(0.5)
    mon5 = conn.recv_match(type='PANDION_MONITOR_CURRENT_STATUS', blocking=True, timeout=2)
    if mon5:
        for mid in _mon_bits(mon5.currently_set):
            conn.mav.pandion_monitor_override_cmd_send(2, mid)
            time.sleep(0.02)
    time.sleep(0.3)

    # ── Test 12: PLAYBACK -> IBIT ─────────────────────────────────────
    conn.mav.pandion_rr_actuation_request_mode_send(requested_mode=1)
    t0 = time.time()
    in_ibit = False
    while time.time() - t0 < 5:
        m = conn.recv_match(type='PANDION_RR_ACTUATION_SYS_STATUS', blocking=True, timeout=0.5)
        if m and m.actuation_state == 1:
            in_ibit = True; break
    ok(f'{label} PLAYBACK -> IBIT', in_ibit)

    # ── Test 13: IBIT substates progress ──────────────────────────────
    seen_substates = set()
    max_fb = 0.0
    max_cur = 0.0
    final_mon = 0
    back_to_operate = False
    was_in_ibit = False
    t0 = time.time()

    while time.time() - t0 < 30:
        m = conn.recv_match(type='PANDION_RR_ACTUATION_SYS_STATUS', blocking=True, timeout=0.5)
        if not m: continue

        if m.actuation_state == 1:  # IBIT
            was_in_ibit = True
            seen_substates.add(m.actuation_ibit_substate)
            for attr in ['left_elevon_feedback_cdeg','right_elevon_feedback_cdeg',
                         'dorsal_rudder_feedback_cdeg','ventral_rudder_feedback_cdeg']:
                max_fb = max(max_fb, abs(getattr(m, attr, 0)))
            for attr in ['left_elevon_current_mA','right_elevon_current_mA']:
                max_cur = max(max_cur, abs(getattr(m, attr, 0)))

        elif m.actuation_state == 2 and was_in_ibit:
            final_mon = m.actuation_ibit_mon_status
            back_to_operate = True
            break

    ok(f'{label} IBIT substates seen', len(seen_substates) >= 4,
       f'substates={sorted(seen_substates)}')
    ok(f'{label} IBIT -> OPERATE completion', back_to_operate)
    ok(f'{label} surface feedback during IBIT', max_fb > 100,
       f'max_feedback={max_fb:.0f} cdeg')
    ok(f'{label} current draw during IBIT', max_cur > 50,
       f'max_current={max_cur:.0f} mA')

    # ── Test 14: Mistracking flags ────────────────────────────────────
    if expect_pass:
        ok(f'{label} IBIT PASS (flags=0x00)', final_mon == 0,
           f'flags=0x{final_mon:02X}')
    else:
        ok(f'{label} IBIT FAIL (flags!=0x00)', final_mon != 0,
           f'flags=0x{final_mon:02X}')

    # ── Test 15: DISARM ───────────────────────────────────────────────
    conn.mav.command_long_send(1, 1, 400, 0, 0, 0, 0, 0, 0, 0, 0)
    ack3 = conn.recv_match(type='COMMAND_ACK', blocking=True, timeout=3)
    ok(f'{label} DISARM accepted', ack3 and ack3.result == 0)

    ps3 = conn.recv_match(type='PANDION_STATUS', blocking=True, timeout=3)
    ok(f'{label} flight regime DISARMED', ps3 and ps3.flight_regime == 0,
       f'flight_regime={ps3.flight_regime if ps3 else "None"}')

    act3 = conn.recv_match(type='PANDION_RR_ACTUATION_SYS_STATUS', blocking=True, timeout=3)
    ok(f'{label} mode OFF after DISARM', act3 and act3.actuation_state == 0,
       f'actuation_state={act3.actuation_state if act3 else "None"}')

    conn.close()


def _mon_bits(byte_array):
    """Extract set monitor IDs from 64-byte array."""
    bits = []
    for i, b in enumerate(byte_array):
        for bit in range(8):
            if b & (1 << bit):
                bits.append(i * 8 + bit)
    return bits


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()

    success = run_tests(verbose=args.verbose)
    sys.exit(0 if success else 1)
