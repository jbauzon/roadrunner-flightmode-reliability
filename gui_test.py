#!/usr/bin/env python3
"""
gui_test.py — Automated GUI test with screenshots.

Launches the full simulator + GUI, drives the test through every
state, and captures timestamped screenshots at each milestone.

Screenshots are saved to ./screenshots/ with descriptive filenames.

Usage:
    python gui_test.py                 # full test
    python gui_test.py --fast          # 4x speed IBIT
    python gui_test.py --screenshots-only  # just open GUI and screenshot
"""

import os
import sys
import time
import json
import threading
import argparse
from datetime import datetime

# ── Path setup ─────────────────────────────────────────────────────────────────
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

DIALECT_DIR = os.path.join(ROOT, "vehicle", "dialects")
sys.path.insert(0, DIALECT_DIR)

# Inject dialect
import importlib
_d = importlib.import_module("pandion_vehicle_roadrunner")
sys.modules["pymavlink.dialects.v10.pandion_vehicle_roadrunner"] = _d
import pymavlink.dialects.v10 as _v10
setattr(_v10, "pandion_vehicle_roadrunner", _d)

SCREENSHOT_DIR = os.path.join(ROOT, "screenshots")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)


def screenshot(window, name):
    """Capture a screenshot of the window and save to screenshots/."""
    from PyQt5.QtWidgets import QApplication
    QApplication.processEvents()
    time.sleep(0.3)
    QApplication.processEvents()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{ts}_{name}.png"
    filepath = os.path.join(SCREENSHOT_DIR, filename)

    # QWidget.grab() works in both offscreen and on-screen modes
    pixmap = window.grab()
    if not pixmap.isNull():
        pixmap.save(filepath, "PNG")
        print(f"[SCREENSHOT] {filename}  ({pixmap.width()}x{pixmap.height()})")
    else:
        print(f"[SCREENSHOT] FAILED — null pixmap for {name}")

    return filepath


def run_test(args):
    """Main test driver."""
    # Force offscreen rendering if no display is available
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PyQt5.QtWidgets import QApplication, QMessageBox
    from PyQt5.QtCore import QTimer, Qt
    from PyQt5.QtGui import QFont

    # ── Inject mocks ──────────────────────────────────────────────────────
    from sim.mock_daq import MockDAQController
    import hardware.daq as daq_module
    daq_module.SimpleDAQController = MockDAQController

    # Patch connect_to_vehicle for sim
    import vehicle.connection as conn_mod
    from pymavlink import mavutil

    def sim_connect(ip_address, port, timeout=10.0):
        connection_string = f"udpout:{ip_address}:{port}"
        master = mavutil.mavlink_connection(
            connection_string,
            dialect="pandion_vehicle_roadrunner",
            source_system=255,
            source_component=190,
        )
        hb = master.wait_heartbeat(timeout=timeout)
        if not hb:
            raise Exception(f"No heartbeat from {ip_address}:{port}")
        return master

    conn_mod.connect_to_vehicle = sim_connect

    # ── Start vehicle sims ────────────────────────────────────────────────
    # Use high ports (29985/29986) to avoid conflicts with other sim sessions
    # that may be using the default 9985/9986 range.
    from sim.vehicle import PandionVehicleSim

    SIM_PORT_1 = 29985
    SIM_PORT_2 = 29986
    scale = 0.25 if args.fast else 0.5

    sims = [
        PandionVehicleSim(
            port=SIM_PORT_1, sysid=1, ibit_pass=True,
            boot_monitors=[0, 1, 2, 3],
            ibit_duration_scale=scale,
        ),
        PandionVehicleSim(
            port=SIM_PORT_2, sysid=2, ibit_pass=False,
            mistracking_flags=192,
            boot_monitors=[0, 1, 5],
            ibit_duration_scale=scale,
        ),
    ]

    for sim in sims:
        # Verify port is free before starting
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.bind(("0.0.0.0", sim.port))
            sock.close()
        except OSError:
            print(f"[TEST] ERROR: Port {sim.port} already in use — another sim session?")
            print(f"[TEST] Aborting to avoid conflicts.")
            sys.exit(1)

        t = threading.Thread(target=sim.start, daemon=True)
        t.start()
    time.sleep(2)
    print("[TEST] Vehicle simulators running")

    # ── Create app + window ───────────────────────────────────────────────
    app = QApplication(sys.argv)
    from ui import theme as T
    T.apply(app)
    app.setFont(QFont("Segoe UI", 10))

    from ui.main_window import MultiUUTTestGUI
    window = MultiUUTTestGUI()

    # Suppress QMessageBox during automated test
    _original_question = QMessageBox.question
    def auto_yes(*a, **kw):
        return QMessageBox.Yes
    QMessageBox.question = auto_yes

    _original_info = QMessageBox.information
    def auto_ok(*a, **kw):
        return QMessageBox.Ok
    QMessageBox.information = auto_ok

    # ── Load UUTs ─────────────────────────────────────────────────────────
    from vehicle.connection import UUT
    window.uuts = [
        UUT(serial_number="RR-SIM-001", ip_address="127.0.0.1", port=SIM_PORT_1, relay_line=0),
        UUT(serial_number="RR-SIM-002", ip_address="127.0.0.1", port=SIM_PORT_2, relay_line=1),
    ]
    window.uut_table_widget.update_table(window.uuts)

    # Auto-init mock DAQ
    window.daq.initialize("SimDAQ/Dev0", num_lines=8)
    window.daq_widget.set_status(True, "SimDAQ Ready (8 lines)")
    window.daq_widget.set_devices(["SimDAQ/Dev0"])

    window.show()
    app.processEvents()
    time.sleep(1)

    # ═══════════════════════════════════════════════════════════════════════
    # Screenshot sequence
    # ═══════════════════════════════════════════════════════════════════════

    captured = []

    def capture(name):
        path = screenshot(window, name)
        captured.append({"name": name, "path": path, "time": datetime.now().isoformat()})

    # 1. Initial state — GUI loaded, UUTs listed, DAQ ready
    capture("01_initial_state")

    if args.screenshots_only:
        # Just show modes and exit
        window.on_test_mode_changed('playback')
        app.processEvents()
        time.sleep(0.5)
        capture("02_playback_mode_selected")
        window.on_test_mode_changed('ibit')
        app.processEvents()
        time.sleep(0.5)
        capture("03_ibit_mode_selected")
        _write_report(captured)
        print(f"\n[TEST] {len(captured)} screenshots saved to {SCREENSHOT_DIR}/")
        return

    # 2. Set duration to 30 seconds for quick test
    window.test_config_widget.duration_input.setValue(30)
    window.test_config_widget.duration_unit_combo.setCurrentText("Seconds")
    app.processEvents()
    capture("02_config_30s_duration")

    # 3. Start the test (auto-confirmed via monkey-patched QMessageBox)
    print("[TEST] Starting IBIT test batch...")
    window.start_all_tests()
    app.processEvents()
    time.sleep(2)
    capture("03_test_started")

    # 4. Wait for first UUT to connect and ARM
    print("[TEST] Waiting for ARM + IBIT...")
    for i in range(10):
        app.processEvents()
        time.sleep(1)
        # Check if IBIT is running
        if hasattr(window, 'current_test_executor') and window.current_test_executor:
            break

    time.sleep(3)
    app.processEvents()
    capture("04_ibit_running")

    # 5. Monitor IBIT progress
    print("[TEST] Monitoring IBIT substates...")
    for i in range(20):
        app.processEvents()
        time.sleep(1)
        if i == 5:
            capture("05_ibit_mid_progress")
        if i == 10:
            capture("06_ibit_late_progress")
        # Check if first UUT completed
        if window.uuts[0].status in ("Complete", "Retry", "Failed (3x)"):
            capture("07_first_uut_complete")
            break

    # 6. Wait for second UUT
    print("[TEST] Waiting for second UUT...")
    for i in range(25):
        app.processEvents()
        time.sleep(1)
        if i == 5:
            capture("08_second_uut_testing")
        if window.uuts[1].status in ("Complete", "Retry", "Failed (3x)"):
            capture("09_second_uut_complete")
            break

    # 7. Wait for batch to finish or time to expire
    print("[TEST] Waiting for batch completion...")
    for i in range(15):
        app.processEvents()
        time.sleep(1)
        if not window.testing_active:
            break

    app.processEvents()
    time.sleep(1)
    capture("10_batch_complete")

    # 8. Check the UUT table for final statuses
    capture("11_final_uut_status")

    # 9. Switch to playback mode and screenshot
    window.on_test_mode_changed('playback')
    app.processEvents()
    time.sleep(0.5)
    capture("12_playback_mode")

    # 10. Switch back to IBIT
    window.on_test_mode_changed('ibit')
    app.processEvents()
    time.sleep(0.5)
    capture("13_ibit_mode_final")

    # Restore QMessageBox
    QMessageBox.question = _original_question
    QMessageBox.information = _original_info

    # Write report
    _write_report(captured)

    print(f"\n{'='*60}")
    print(f"  TEST COMPLETE — {len(captured)} screenshots captured")
    print(f"  Screenshots: {SCREENSHOT_DIR}")
    print(f"{'='*60}")


def _write_report(captured):
    """Write a JSON report of all captured screenshots."""
    report = {
        "test_run": datetime.now().isoformat(),
        "screenshot_dir": SCREENSHOT_DIR,
        "total_screenshots": len(captured),
        "screenshots": captured,
    }
    report_path = os.path.join(SCREENSHOT_DIR, "test_report.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"[TEST] Report: {report_path}")


def main():
    parser = argparse.ArgumentParser(description="Automated GUI test with screenshots")
    parser.add_argument("--fast", action="store_true", help="4x speed IBIT phases")
    parser.add_argument("--screenshots-only", action="store_true",
                        help="Just open GUI, take a few screenshots, exit")
    args = parser.parse_args()
    run_test(args)


if __name__ == "__main__":
    main()
