#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_sim.py -- Roadrunner Flight Test full simulation launcher.

Starts one simulated Pandion vehicle per UUT entry in sim_config.yaml,
each listening on its own UDP port sending real MAVLink packets.
Then launches the test software GUI with the MockDAQController injected
so no physical NI-DAQmx hardware is needed.

Usage:
    python run_sim.py                        # use sim_config.yaml defaults
    python run_sim.py --config my_sim.yaml   # custom config
    python run_sim.py --no-gui               # vehicles only, no GUI (for CI)

sim_config.yaml example:
    vehicles:
      - serial: RR-SIM-001
        ip: 127.0.0.1
        port: 9985
        relay_line: 0
        ibit_pass: true
        boot_monitors: [0, 1, 2, 3]

      - serial: RR-SIM-002
        ip: 127.0.0.1
        port: 9986
        relay_line: 1
        ibit_pass: false
        mistracking_flags: 192   # 0xC0 = LEFT_ELEVON + RIGHT_ELEVON
        boot_monitors: [0, 1, 5]
"""

import os
import sys
import time
import threading
import argparse

import yaml

# Force UTF-8 output on Windows consoles (cp1252 can't handle unicode)
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# ── Path setup ────────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = _HERE  # run_sim.py lives at project root
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def load_config(config_path):
    with open(config_path) as f:
        return yaml.safe_load(f)


def start_vehicle(vcfg, verbose=False, fleet=None):
    """Start a simulated vehicle (single udpout connection)."""
    from rr_test.sim.vehicle import PandionVehicleSim

    sim = PandionVehicleSim(
        vehicle_port=vcfg['port'],
        sysid=vcfg.get('sysid', 1),
        ibit_pass=vcfg.get('ibit_pass', True),
        mistracking_flags=vcfg.get('mistracking_flags', 0),
        boot_monitors=vcfg.get('boot_monitors', [0, 1, 2, 3]),
        post_arm_monitors=vcfg.get('post_arm_monitors', [10]),
        transient_monitor_chance=vcfg.get('transient_monitor_chance', 0.1),
        ibit_duration_scale=vcfg.get('ibit_duration_scale', 1.0),
        ibit_cycles=vcfg.get('ibit_cycles', 1),
        boot_time_s=vcfg.get('boot_time_s', 3.0),
        eval_window_s=vcfg.get('eval_window_s', 0.6),
        packet_drop_rate=vcfg.get('packet_drop_rate', 0.0),
        verbose=verbose,
        fleet=fleet,
    )
    if fleet:
        fleet.add(sim)
    t = threading.Thread(target=sim.start, daemon=True, name=f"sim-{vcfg['port']}")
    t.start()
    return sim, t


def inject_mock_daq():
    """Replace SimpleDAQController with MockDAQController globally."""
    from rr_test.sim.mock_daq import MockDAQController
    import rr_test.hardware.daq as daq_module
    daq_module.SimpleDAQController = MockDAQController
    print("[Launcher] MockDAQController injected - no NI-DAQmx hardware needed")


def patch_loopback_for_sim():
    """
    Patch connect_to_vehicle to allow loopback addresses in sim mode.

    Production code rejects 127.x.x.x for safety. In sim mode we need
    loopback because the sim vehicles run on localhost. This patch ONLY
    runs when launched via run_sim.py — production code is never modified.
    """
    import rr_test.vehicle.connection as conn_mod
    _original = conn_mod.connect_to_vehicle

    def _sim_connect(ip_address, port, timeout=10.0):
        import ipaddress
        ip = ipaddress.ip_address(ip_address)
        if ip.is_multicast:
            raise ValueError("Multicast addresses not allowed")

        script_dir = os.path.dirname(os.path.abspath(conn_mod.__file__))
        dialect_dir = os.path.join(script_dir, "dialects")
        if dialect_dir not in sys.path:
            sys.path.insert(0, dialect_dir)

        from pymavlink import mavutil
        # Use udpout: test SW sends TO the sim's udpin port.
        # Sim binds on vehicle_port with udpin, we connect with udpout.
        # This avoids Windows CONNRESET because the sim is already bound.
        connection_string = f"udpout:{str(ip)}:{port}"
        master = mavutil.mavlink_connection(
            connection_string,
            dialect="pandion_vehicle_roadrunner",
            source_system=255,
            source_component=190,
        )

        # Send initial heartbeats so the sim knows our return address
        for _ in range(5):
            try:
                master.mav.heartbeat_send(
                    mavutil.mavlink.MAV_TYPE_GCS,
                    mavutil.mavlink.MAV_AUTOPILOT_INVALID,
                    0, 0,
                    mavutil.mavlink.MAV_STATE_ACTIVE)
            except OSError:
                pass
            hb = master.recv_match(type='HEARTBEAT', blocking=True, timeout=1.0)
            if hb and hb.get_srcSystem() != 255:
                return master

        raise Exception(
            f"Connection timeout after {timeout}s - "
            f"no heartbeat from {ip_address}:{port}"
        )

    conn_mod.connect_to_vehicle = _sim_connect
    print("[Launcher] connect_to_vehicle patched - loopback allowed for sim")


def pre_populate_uuts(vehicles):
    """
    Write a uut_config.json with the simulated vehicles so the GUI
    loads them automatically without manual entry.
    """
    import json
    cfg = {
        'uuts': [
            {
                'serial_number': v['serial'],
                'ip_address':    v['ip'],
                'port':          v['port'],
                'relay_line':    v['relay_line'],
            }
            for v in vehicles
        ]
    }
    out_path = os.path.join(_ROOT, 'sim_uut_config.json')
    with open(out_path, 'w') as f:
        json.dump(cfg, f, indent=2)
    print(f"[Launcher] UUT config written: {out_path}")
    return out_path


def launch_gui(uut_config_path):
    """Launch the test software GUI with mock DAQ."""
    from PyQt5.QtWidgets import QApplication
    from PyQt5.QtGui import QFont
    from ui.main_window import MultiUUTTestGUI
    from ui import theme as T
    import json

    app = QApplication(sys.argv)
    T.apply(app)
    app.setFont(QFont("Segoe UI", 10))

    window = MultiUUTTestGUI()

    # Auto-load the simulated UUT config
    with open(uut_config_path) as f:
        cfg = json.load(f)
    from rr_test.vehicle.connection import UUT
    window.uuts = [UUT.from_dict(d) for d in cfg['uuts']]
    window.uut_table_widget.update_table(window.uuts)
    window.log(f"[SIM] Loaded {len(window.uuts)} simulated UUT(s) from {uut_config_path}")
    window.log("[SIM] MockDAQ active — relay calls are simulated")
    window.log("[SIM] Vehicle simulators running on localhost — real UDP packets")

    # Auto-initialize mock DAQ
    window.daq.initialize("SimDAQ/Dev0", num_lines=8)
    window.daq_widget.set_status(True, "SimDAQ Ready  (8 lines)")
    window.daq_widget.set_devices(["SimDAQ/Dev0"])

    window.show()
    sys.exit(app.exec_())


def main():
    parser = argparse.ArgumentParser(description="Roadrunner Flight Test Simulator")
    parser.add_argument(
        '--config', default=os.path.join(_ROOT, 'sim', 'sim_config.yaml'),
        help="Path to sim_config.yaml"
    )
    parser.add_argument(
        '--no-gui', action='store_true',
        help="Start vehicle sims only, no GUI (useful for CI)"
    )
    parser.add_argument(
        '--verbose', action='store_true',
        help="Print every MAVLink message"
    )
    args = parser.parse_args()

    if not os.path.exists(args.config):
        print(f"[Launcher] Config not found: {args.config}")
        print("[Launcher] Creating default sim_config.yaml...")
        _write_default_config(args.config)

    cfg = load_config(args.config)
    vehicles = cfg.get('vehicles', [])

    if not vehicles:
        print("[Launcher] No vehicles defined in config. Exiting.")
        sys.exit(1)

    print(f"[Launcher] Starting {len(vehicles)} vehicle simulator(s)...")

    # Inject mock DAQ (no NI-DAQmx hardware needed)
    inject_mock_daq()

    # Allow loopback addresses for sim mode
    patch_loopback_for_sim()

    from rr_test.sim.fleet import SimFleet
    fleet = SimFleet()

    sims = []
    for v in vehicles:
        sim, thread = start_vehicle(v, verbose=args.verbose, fleet=fleet)
        sims.append((sim, thread))
        time.sleep(0.3)

    print(f"[Launcher] All {len(sims)} simulators running (fleet size={len(fleet.vehicles)})")

    if args.no_gui:
        print("[Launcher] --no-gui mode — press Ctrl+C to stop")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("[Launcher] Stopped.")
        return

    # Pre-populate UUT config JSON
    uut_config_path = pre_populate_uuts(vehicles)

    # Small delay to let simulators bind and start sending
    print("[Launcher] Waiting for simulators to start...")
    time.sleep(1.5)

    # Launch GUI
    print("[Launcher] Launching test software GUI...")
    launch_gui(uut_config_path)


def _write_default_config(path):
    default = {
        'vehicles': [
            {
                'serial':             'RR-SIM-001',
                'ip':                 '127.0.0.1',
                'port':               19901,
                'relay_line':         0,
                'sysid':              1,
                'ibit_pass':          True,
                'boot_monitors':      [0, 1, 2, 3],
                'ibit_duration_scale':1.0,
            },
            {
                'serial':             'RR-SIM-002',
                'ip':                 '127.0.0.1',
                'port':               19902,
                'relay_line':         1,
                'sysid':              2,
                'ibit_pass':          False,
                'mistracking_flags':  192,
                'boot_monitors':      [0, 1, 5],
                'ibit_duration_scale':1.0,
            },
        ]
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        yaml.dump(default, f, default_flow_style=False)
    print(f"[Launcher] Default config written → {path}")


if __name__ == '__main__':
    main()
