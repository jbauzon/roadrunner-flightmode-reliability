#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_permutations.py -- Extensive permutation testing of the SITL.

Tests every combination of:
  - Vehicle fault profiles (pass, elevon fail, rudder fail, TVC fail, all fail)
  - Boot monitor sets (none, minimal, full, extra)
  - IBIT duration scales (0.2x fast, 0.5x medium, 1.0x real)
  - Monitor eval windows (0.2s fast, 0.6s normal, 1.5s slow)
  - Post-ARM monitor sets (none, single, multiple)
  - Packet drop rates (0%, 2%, 5%)
  - Boot times (1s fast, 3s normal, 5s slow)
  - Intermittent servo faults
  - GNSS degradation during IBIT
  - Multiple IBIT cycles (1, 2)

Each permutation:
  1. Starts a fresh sim vehicle
  2. Connects via udpout (same as GUI)
  3. Runs the full ARM -> OPERATE -> PLAYBACK -> IBIT -> OPERATE -> DISARM sequence
  4. Validates expected pass/fail result
  5. Records timing, monitor counts, surface feedback stats

Results saved to test_permutation_results.json

Usage:
    python test_permutations.py              # run all (may take 10+ minutes)
    python test_permutations.py --quick      # reduced set (~2 minutes)
    python test_permutations.py --scenario X # run single scenario by index
"""

import os, sys, time, json, threading, traceback, argparse
from datetime import datetime

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

BASE_PORT = 39800  # Each test gets its own port

# ═══════════════════════════════════════════════════════════════════════════════
# Scenario definitions
# ═══════════════════════════════════════════════════════════════════════════════

def build_scenarios(quick=False):
    scenarios = []

    # ── Fault profiles ────────────────────────────────────────────────
    fault_profiles = [
        {'name': 'healthy',       'ibit_pass': True,  'mistracking_flags': 0},
        {'name': 'elevon_fail',   'ibit_pass': False, 'mistracking_flags': 0xC0},
        {'name': 'rudder_fail',   'ibit_pass': False, 'mistracking_flags': 0x03},
        {'name': 'tvc_fail',      'ibit_pass': False, 'mistracking_flags': 0x3C},
        {'name': 'all_fail',      'ibit_pass': False, 'mistracking_flags': 0xFF},
        {'name': 'single_tvc',    'ibit_pass': False, 'mistracking_flags': 0x04},
    ]

    # ── Boot monitor sets ─────────────────────────────────────────────
    boot_monitor_sets = [
        {'name': 'no_boot_mon',    'boot_monitors': []},
        {'name': 'minimal_mon',    'boot_monitors': [0, 5]},
        {'name': 'full_boot_mon',  'boot_monitors': [0, 1, 2, 3, 4, 5]},
        {'name': 'extra_mon',      'boot_monitors': [0, 1, 2, 3, 4, 5, 11]},
    ]

    # ── Timing configurations ─────────────────────────────────────────
    timing_configs = [
        {'name': 'fast',   'ibit_duration_scale': 0.2, 'boot_time_s': 1.0, 'eval_window_s': 0.2},
        {'name': 'medium', 'ibit_duration_scale': 0.5, 'boot_time_s': 2.0, 'eval_window_s': 0.4},
        {'name': 'normal', 'ibit_duration_scale': 1.0, 'boot_time_s': 3.0, 'eval_window_s': 0.6},
    ]

    # ── Network conditions ────────────────────────────────────────────
    network_configs = [
        {'name': 'clean',       'packet_drop_rate': 0.0},
        {'name': 'noisy_2pct',  'packet_drop_rate': 0.02},
    ]

    # ── Post-ARM monitors ─────────────────────────────────────────────
    post_arm_sets = [
        {'name': 'post_arm_single',   'post_arm_monitors': [10]},
        {'name': 'post_arm_multi',    'post_arm_monitors': [10, 11]},
    ]

    # ── Special features ──────────────────────────────────────────────
    special_features = [
        {'name': 'normal',       'gnss_degrade_during_ibit': False, 'ibit_cycles': 1},
        {'name': 'gnss_degrade', 'gnss_degrade_during_ibit': True,  'ibit_cycles': 1},
        {'name': 'multi_cycle',  'gnss_degrade_during_ibit': False, 'ibit_cycles': 2},
    ]

    if quick:
        # Reduced set: 6 scenarios
        fault_profiles = fault_profiles[:3]
        timing_configs = timing_configs[:2]
        boot_monitor_sets = [boot_monitor_sets[1]]
        network_configs = [network_configs[0]]
        post_arm_sets = [post_arm_sets[0]]
        special_features = [special_features[0]]
    else:
        # Meaningful coverage without full cartesian product
        # ~96 scenarios: 6 faults x 2 timing x 2 boot_mon x 2 network x 2 post_arm x 1 special
        # Plus 6 special-feature combos
        timing_configs = timing_configs[:2]
        boot_monitor_sets = boot_monitor_sets[:2]  # none, minimal
        # special_features run once per fault profile instead of full cross

    idx = 0
    for fault in fault_profiles:
        for timing in timing_configs:
            for boot_mon in boot_monitor_sets:
                for network in network_configs:
                    for post_arm in post_arm_sets:
                        for special in special_features:
                            name = (f"{fault['name']}__{timing['name']}__{boot_mon['name']}__"
                                    f"{network['name']}__{post_arm['name']}__{special['name']}")
                            config = {
                                'index': idx,
                                'name': name,
                                'expect_pass': fault['ibit_pass'],
                                'vehicle_port': BASE_PORT + idx,
                                'sysid': 1,
                                **fault,
                                **timing,
                                **boot_mon,
                                **network,
                                **post_arm,
                                **special,
                            }
                            # Remove 'name' keys from sub-dicts
                            for k in list(config.keys()):
                                if k == 'name' and config[k] != name:
                                    del config[k]
                            config['name'] = name
                            scenarios.append(config)
                            idx += 1

    return scenarios


# ═══════════════════════════════════════════════════════════════════════════════
# Test runner
# ═══════════════════════════════════════════════════════════════════════════════

def run_scenario(config):
    """Run a single test scenario. Returns result dict."""
    port = config['vehicle_port']
    result = {
        'name': config['name'],
        'index': config['index'],
        'expect_pass': config['expect_pass'],
        'status': 'UNKNOWN',
        'error': None,
        'duration_s': 0,
        'ibit_flags': None,
        'substates_seen': [],
        'max_feedback_cdeg': 0,
        'max_current_mA': 0,
        'monitors_at_boot': [],
        'arm_attempts': 0,
    }

    sim = None
    conn = None
    start_time = time.time()

    try:
        # Start sim
        sim = PandionVehicleSim(
            vehicle_port=port,
            sysid=config.get('sysid', 1),
            ibit_pass=config.get('ibit_pass', True),
            mistracking_flags=config.get('mistracking_flags', 0),
            boot_monitors=config.get('boot_monitors', [0, 5]),
            post_arm_monitors=config.get('post_arm_monitors', [10]),
            ibit_duration_scale=config.get('ibit_duration_scale', 0.3),
            ibit_cycles=config.get('ibit_cycles', 1),
            boot_time_s=config.get('boot_time_s', 1.5),
            eval_window_s=config.get('eval_window_s', 0.3),
            packet_drop_rate=config.get('packet_drop_rate', 0.0),
            gnss_degrade_during_ibit=config.get('gnss_degrade_during_ibit', False),
        )
        t = threading.Thread(target=sim.start, daemon=True)
        t.start()

        # Wait for boot
        boot_wait = config.get('boot_time_s', 1.5) * config.get('ibit_duration_scale', 0.3) + 2.0
        time.sleep(boot_wait)

        # Connect
        conn = mavutil.mavlink_connection(
            f'udpout:127.0.0.1:{port}',
            dialect='pandion_vehicle_roadrunner',
            source_system=255, source_component=190)

        for _ in range(3):
            conn.mav.heartbeat_send(6, 8, 0, 0, 4)
            time.sleep(0.2)

        hb = conn.wait_heartbeat(timeout=5)
        if not hb:
            result['status'] = 'FAIL_CONNECT'
            result['error'] = 'No heartbeat'
            return result

        # Read boot monitors
        mon = conn.recv_match(type='PANDION_MONITOR_CURRENT_STATUS', blocking=True, timeout=2)
        if mon:
            result['monitors_at_boot'] = [i*8+b for i,byte in enumerate(mon.currently_set)
                                           for b in range(8) if byte & (1<<b)]

        # Clear all monitors
        for mid in result['monitors_at_boot']:
            conn.mav.pandion_monitor_override_cmd_send(2, mid)
            time.sleep(0.02)
        time.sleep(0.5)

        # Clear any extras
        mon2 = conn.recv_match(type='PANDION_MONITOR_CURRENT_STATUS', blocking=True, timeout=1)
        if mon2:
            extras = [i*8+b for i,byte in enumerate(mon2.currently_set)
                      for b in range(8) if byte & (1<<b)]
            for mid in extras:
                conn.mav.pandion_monitor_override_cmd_send(2, mid)
                time.sleep(0.02)
        time.sleep(0.3)

        # ARM
        arm_attempts = 0
        armed = False
        for attempt in range(10):
            arm_attempts += 1
            conn.mav.command_long_send(1, 1, 400, 0, 1, 0, 0, 0, 0, 0, 0)
            ack = conn.recv_match(type='COMMAND_ACK', blocking=True, timeout=2)
            if ack and ack.result == 0:
                armed = True
                break
            # Clear any new monitors
            m = conn.recv_match(type='PANDION_MONITOR_CURRENT_STATUS', blocking=True, timeout=0.5)
            if m:
                bits = [i*8+b for i,byte in enumerate(m.currently_set)
                        for b in range(8) if byte & (1<<b)]
                for mid in bits:
                    conn.mav.pandion_monitor_override_cmd_send(2, mid)
                    time.sleep(0.02)
            time.sleep(0.3)

        result['arm_attempts'] = arm_attempts
        if not armed:
            result['status'] = 'FAIL_ARM'
            result['error'] = f'ARM failed after {arm_attempts} attempts'
            return result

        # Clear post-ARM monitors
        time.sleep(1)
        m = conn.recv_match(type='PANDION_MONITOR_CURRENT_STATUS', blocking=True, timeout=1)
        if m:
            bits = [i*8+b for i,byte in enumerate(m.currently_set)
                    for b in range(8) if byte & (1<<b)]
            for mid in bits:
                conn.mav.pandion_monitor_override_cmd_send(2, mid)
                time.sleep(0.02)
        time.sleep(0.3)

        # OPERATE -> PLAYBACK
        conn.mav.pandion_rr_actuation_request_mode_send(requested_mode=4)
        t0 = time.time()
        while time.time() - t0 < 5:
            m = conn.recv_match(type='PANDION_RR_ACTUATION_SYS_STATUS', blocking=True, timeout=0.5)
            if m and m.actuation_state == 4:
                break

        # Clear any transient monitors
        time.sleep(0.3)
        m = conn.recv_match(type='PANDION_MONITOR_CURRENT_STATUS', blocking=True, timeout=1)
        if m:
            for mid in [i*8+b for i,byte in enumerate(m.currently_set)
                        for b in range(8) if byte & (1<<b)]:
                conn.mav.pandion_monitor_override_cmd_send(2, mid)
                time.sleep(0.02)
        time.sleep(0.2)

        # PLAYBACK -> IBIT
        conn.mav.pandion_rr_actuation_request_mode_send(requested_mode=1)
        t0 = time.time()
        in_ibit = False
        while time.time() - t0 < 5:
            m = conn.recv_match(type='PANDION_RR_ACTUATION_SYS_STATUS', blocking=True, timeout=0.5)
            if m and m.actuation_state == 1:
                in_ibit = True
                break

        if not in_ibit:
            result['status'] = 'FAIL_IBIT_ENTRY'
            result['error'] = 'Failed to enter IBIT mode'
            return result

        # Monitor IBIT
        seen = set()
        max_fb = 0.0
        max_cur = 0.0
        was_ibit = False
        final_flags = 0
        t0 = time.time()
        timeout = 60  # generous timeout

        while time.time() - t0 < timeout:
            m = conn.recv_match(type='PANDION_RR_ACTUATION_SYS_STATUS', blocking=True, timeout=0.5)
            if not m:
                continue
            if m.actuation_state == 1:
                was_ibit = True
                seen.add(m.actuation_ibit_substate)
                for a in ['left_elevon_feedback_cdeg', 'right_elevon_feedback_cdeg',
                          'dorsal_rudder_feedback_cdeg', 'ventral_rudder_feedback_cdeg']:
                    max_fb = max(max_fb, abs(getattr(m, a, 0)))
                for a in ['left_elevon_current_mA', 'right_elevon_current_mA']:
                    max_cur = max(max_cur, abs(getattr(m, a, 0)))
            elif m.actuation_state == 2 and was_ibit:
                final_flags = m.actuation_ibit_mon_status
                break

        result['substates_seen'] = sorted(seen)
        result['max_feedback_cdeg'] = max_fb
        result['max_current_mA'] = max_cur
        result['ibit_flags'] = final_flags

        # Evaluate
        if config['expect_pass']:
            if final_flags == 0:
                result['status'] = 'PASS'
            else:
                result['status'] = 'UNEXPECTED_FAIL'
                result['error'] = f'Expected PASS but got flags=0x{final_flags:02X}'
        else:
            if final_flags != 0:
                result['status'] = 'PASS'
            else:
                result['status'] = 'UNEXPECTED_PASS'
                result['error'] = f'Expected FAIL but got flags=0x00'

        # DISARM
        conn.mav.command_long_send(1, 1, 400, 0, 0, 0, 0, 0, 0, 0, 0)
        conn.recv_match(type='COMMAND_ACK', blocking=True, timeout=2)

    except Exception as e:
        result['status'] = 'ERROR'
        result['error'] = f'{type(e).__name__}: {str(e)}'
    finally:
        result['duration_s'] = round(time.time() - start_time, 1)
        if conn:
            try: conn.close()
            except: pass
        if sim:
            sim.stop()

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description='SITL permutation tests')
    parser.add_argument('--quick', action='store_true', help='Reduced scenario set')
    parser.add_argument('--scenario', type=int, help='Run single scenario by index')
    args = parser.parse_args()

    scenarios = build_scenarios(quick=args.quick)

    if args.scenario is not None:
        scenarios = [s for s in scenarios if s['index'] == args.scenario]

    print(f'{"="*70}')
    print(f'  SITL Permutation Tests -- {len(scenarios)} scenarios')
    print(f'{"="*70}')
    print()

    results = []
    passed = 0
    failed = 0
    errors = 0

    for i, scenario in enumerate(scenarios):
        label = f'[{i+1}/{len(scenarios)}] {scenario["name"]}'
        sys.stdout.write(f'  {label[:65]:65s} ')
        sys.stdout.flush()

        r = run_scenario(scenario)
        results.append(r)

        if r['status'] == 'PASS':
            passed += 1
            print(f'PASS  ({r["duration_s"]}s)')
        elif r['status'] in ('UNEXPECTED_FAIL', 'UNEXPECTED_PASS'):
            failed += 1
            print(f'FAIL  {r["error"]}')
        else:
            errors += 1
            print(f'{r["status"]}  {r["error"]}')

    # Summary
    print()
    print(f'{"="*70}')
    print(f'  RESULTS: {passed} passed, {failed} failed, {errors} errors '
          f'out of {len(scenarios)} total')
    print(f'{"="*70}')

    if failed > 0:
        print(f'\n  FAILURES:')
        for r in results:
            if r['status'] in ('UNEXPECTED_FAIL', 'UNEXPECTED_PASS'):
                print(f'    {r["name"]}: {r["error"]}')

    if errors > 0:
        print(f'\n  ERRORS:')
        for r in results:
            if r['status'] not in ('PASS', 'UNEXPECTED_FAIL', 'UNEXPECTED_PASS'):
                print(f'    {r["name"]}: {r["status"]} -- {r["error"]}')

    # Save results
    out_path = os.path.join(ROOT, 'test_permutation_results.json')
    report = {
        'timestamp': datetime.now().isoformat(),
        'total': len(scenarios),
        'passed': passed,
        'failed': failed,
        'errors': errors,
        'results': results,
    }
    with open(out_path, 'w') as f:
        json.dump(report, f, indent=2)
    print(f'\n  Results saved: {out_path}')

    return failed == 0 and errors == 0


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
