"""
test_gui_live.py -- Launch GUI on real Windows display with SITL,
run IBIT test, take screenshots at each phase for visual validation.

This runs with the actual Windows display (not offscreen) so you can
see the GUI while it operates.
"""
import os, sys, time, threading, json

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

SHOTS = os.path.join(ROOT, 'screenshots')
os.makedirs(SHOTS, exist_ok=True)

from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QFont
from PyQt5.QtCore import QTimer


def shot(win, name):
    p = os.path.join(SHOTS, f'live_{name}.png')
    px = win.grab()
    px.save(p, 'PNG')
    print(f"  Screenshot: {name}  ({px.width()}x{px.height()})")


def main():
    # ── Patch for sim ────────────────────────────────────────────────
    from sim.vehicle import PandionVehicleSim
    from sim.fleet import SimFleet
    from sim.mock_daq import MockDAQController
    import hardware.daq as daq_mod
    import vehicle.connection as conn_mod

    daq_mod.SimpleDAQController = MockDAQController

    def _sim_connect(ip, port, timeout=10.0):
        d = os.path.join(os.path.dirname(os.path.abspath(conn_mod.__file__)), "dialects")
        if d not in sys.path:
            sys.path.insert(0, d)
        from pymavlink import mavutil
        m = mavutil.mavlink_connection(
            f"udpout:{ip}:{port}", dialect="pandion_vehicle_roadrunner",
            source_system=255, source_component=190)
        for _ in range(5):
            try:
                m.mav.heartbeat_send(
                    mavutil.mavlink.MAV_TYPE_GCS,
                    mavutil.mavlink.MAV_AUTOPILOT_INVALID,
                    0, 0, mavutil.mavlink.MAV_STATE_ACTIVE)
            except OSError:
                pass
            hb = m.recv_match(type='HEARTBEAT', blocking=True, timeout=1.0)
            if hb and hb.get_srcSystem() != 255:
                return m
        raise Exception(f"No heartbeat from {ip}:{port}")
    conn_mod.connect_to_vehicle = _sim_connect

    # ── Start SITL ───────────────────────────────────────────────────
    print("Starting SITL vehicles...")
    fleet = SimFleet()
    vcfgs = [
        {'serial': 'RR-SIM-001', 'ip': '127.0.0.1', 'port': 19901,
         'relay_line': 0, 'sysid': 1, 'ibit_pass': True,
         'boot_monitors': [0, 1, 2, 3], 'ibit_duration_scale': 0.3,
         'boot_time_s': 1.5},
        {'serial': 'RR-SIM-002', 'ip': '127.0.0.1', 'port': 19902,
         'relay_line': 1, 'sysid': 2, 'ibit_pass': False,
         'mistracking_flags': 192, 'boot_monitors': [0, 1, 5],
         'ibit_duration_scale': 0.3, 'boot_time_s': 1.5},
    ]
    sims = []
    for v in vcfgs:
        sim = PandionVehicleSim(
            vehicle_port=v['port'], sysid=v.get('sysid', 1),
            ibit_pass=v.get('ibit_pass', True),
            mistracking_flags=v.get('mistracking_flags', 0),
            boot_monitors=v.get('boot_monitors', []),
            ibit_duration_scale=v.get('ibit_duration_scale', 1.0),
            boot_time_s=v.get('boot_time_s', 3.0), fleet=fleet)
        fleet.add(sim)
        threading.Thread(target=sim.start, daemon=True).start()
        sims.append(sim)
        time.sleep(0.3)
    print(f"  {len(sims)} vehicles booting...")
    time.sleep(3.0)
    print("  SITL ready")

    # ── Launch GUI ───────────────────────────────────────────────────
    app = QApplication(sys.argv)
    from ui import theme as T
    T.apply(app)
    app.setFont(QFont("Segoe UI", 10))

    from ui.main_window import MultiUUTTestGUI
    from vehicle.connection import UUT

    win = MultiUUTTestGUI()
    win.uuts = [UUT.from_dict({
        'serial_number': v['serial'], 'ip_address': v['ip'],
        'port': v['port'], 'relay_line': v['relay_line'],
    }) for v in vcfgs]
    win.uut_table_widget.update_table(win.uuts)
    win.daq.initialize("SimDAQ/Dev0", num_lines=8)
    win.daq_widget.set_status(True, "SimDAQ Ready (8 lines)")
    win.daq_widget.set_devices(["SimDAQ/Dev0"])
    win.show()

    # ── Sequenced test via timers ────────────────────────────────────
    step = [0]
    last_status = [None]

    def tick():
        s = step[0]

        if s == 0:
            shot(win, '01_initial')
            print("Starting IBIT test...")
            win._auto_start_test(120)
            step[0] = 1

        elif s == 1:
            if win.testing_active:
                shot(win, '02_test_started')
                step[0] = 2

        elif s == 2:
            # Monitor UUT 0 -- screenshot on status changes
            if win.uuts[0].status != last_status[0]:
                last_status[0] = win.uuts[0].status
                safe = last_status[0].replace(" ", "_").replace("(", "").replace(")", "").lower()[:12]
                shot(win, f'03_{safe}')

            if win.uuts[0].status in ("Complete", "Failed", "Failed (3x)", "Retry"):
                shot(win, '04_uut0_result')
                step[0] = 3
                last_status[0] = None

        elif s == 3:
            # Monitor UUT 1
            if len(win.uuts) > 1 and win.uuts[1].status != last_status[0]:
                last_status[0] = win.uuts[1].status
                safe = last_status[0].replace(" ", "_").replace("(", "").replace(")", "").lower()[:12]
                shot(win, f'05_{safe}')

            if len(win.uuts) > 1 and win.uuts[1].status in (
                    "Complete", "Failed", "Retry", "Failed (3x)"):
                shot(win, '06_uut1_result')
                step[0] = 4

        elif s == 4:
            shot(win, '07_final')
            print("\nTest complete. Stopping in 5s...")
            step[0] = 5

        elif s == 5:
            step[0] = 6
            QTimer.singleShot(5000, lambda: _shutdown(win, sims, app, timer))

    def _shutdown(win, sims, app, timer):
        timer.stop()
        win.testing_active = False
        if win.current_test_executor:
            win.current_test_executor.stop()
        for sim in sims:
            sim.stop()
        shot(win, '08_shutdown')
        print("\nAll screenshots saved to screenshots/live_*.png")
        print("Closing in 3s...")
        QTimer.singleShot(3000, app.quit)

    timer = QTimer()
    timer.timeout.connect(tick)
    # First tick after 2s to let the window render
    QTimer.singleShot(2000, lambda: timer.start(500))

    app.exec_()
    print("Done.")


if __name__ == '__main__':
    main()
