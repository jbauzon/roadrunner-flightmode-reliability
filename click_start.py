#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
click_start.py -- Remote control tool for the Flight Test GUI.

Communicates with the GUI over a local TCP socket. No mouse simulation,
no window focus issues, works reliably from any terminal.

Commands:
    python click_start.py start              Start IBIT test (120s default)
    python click_start.py start 60           Start IBIT test (60s)
    python click_start.py stop               Stop current test
    python click_start.py emergency          Emergency stop all relays
    python click_start.py status             Get test status
    python click_start.py screenshot         Take a GUI screenshot
    python click_start.py set_duration 300   Set duration to 300 seconds
    python click_start.py watch              Poll status every 2s until test ends
    python click_start.py run_and_watch 120  Start test, poll, take screenshots
"""
import socket
import sys
import json
import time
import os

PORT = 18888
SCREENSHOT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'screenshots')


def send_command(cmd, args=None, timeout=30):
    """Send a command to the GUI's command server."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect(('127.0.0.1', PORT))
        payload = json.dumps({'cmd': cmd, 'args': args or {}})
        sock.sendall(payload.encode('utf-8'))
        response = sock.recv(65536).decode('utf-8')
        return json.loads(response)
    except ConnectionRefusedError:
        return {'error': 'GUI not running or command server not started'}
    except socket.timeout:
        return {'error': 'Command timed out'}
    finally:
        sock.close()


def cmd_start(duration=120):
    print(f"Starting IBIT test ({duration}s)...")
    r = send_command('start', {'seconds': duration})
    print(json.dumps(r, indent=2))
    return r.get('ok', False)


def cmd_stop():
    print("Stopping test...")
    r = send_command('stop')
    print(json.dumps(r, indent=2))


def cmd_emergency():
    print("EMERGENCY STOP...")
    r = send_command('emergency')
    print(json.dumps(r, indent=2))


def cmd_status():
    r = send_command('status')
    if 'error' in r:
        print(f"Error: {r['error']}")
        return r

    print(f"  Testing: {r.get('testing', False)}")
    print(f"  Mode:    {r.get('mode', '?')}")
    print(f"  Elapsed: {r.get('elapsed', 0):.0f}s")
    for u in r.get('uuts', []):
        print(f"  UUT {u['serial']:15s}  status={u['status']:12s}  iterations={u['iterations']}")
    return r


def cmd_screenshot():
    r = send_command('screenshot')
    if r.get('ok'):
        print(f"Screenshot: {r['path']}  ({r['size']})")
    else:
        print(f"Error: {r.get('error', 'unknown')}")
    return r


def cmd_watch(interval=2):
    """Poll status until test completes."""
    print("Watching test progress (Ctrl+C to stop)...")
    shot_count = 0
    try:
        while True:
            r = send_command('status')
            if 'error' in r:
                print(f"  Error: {r['error']}")
                time.sleep(interval)
                continue

            testing = r.get('testing', False)
            elapsed = r.get('elapsed', 0)
            uuts = r.get('uuts', [])
            statuses = ', '.join(f"{u['serial']}={u['status']}" for u in uuts)
            print(f"  [{elapsed:6.0f}s] testing={testing}  {statuses}")

            # Auto-screenshot every 15s
            if testing and int(elapsed) % 15 < interval:
                shot_count += 1
                sr = send_command('screenshot')
                if sr.get('ok'):
                    print(f"         Screenshot #{shot_count}: {os.path.basename(sr['path'])}")

            if not testing and elapsed > 0:
                print("\n  Test complete.")
                # Final screenshot
                send_command('screenshot')
                break

            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n  Watch stopped.")


def cmd_run_and_watch(duration=120):
    """Start test, watch progress, take screenshots."""
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)

    # Screenshot before start
    send_command('screenshot')
    print("Pre-test screenshot saved\n")

    # Start
    if not cmd_start(duration):
        print("Failed to start test")
        return

    time.sleep(2)
    cmd_watch(interval=3)

    # Final screenshot
    time.sleep(2)
    send_command('screenshot')
    print("\nFinal screenshot saved")
    print(f"All screenshots in: {SCREENSHOT_DIR}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    cmd = sys.argv[1]

    if cmd == 'start':
        dur = int(sys.argv[2]) if len(sys.argv) > 2 else 120
        cmd_start(dur)
    elif cmd == 'stop':
        cmd_stop()
    elif cmd == 'emergency':
        cmd_emergency()
    elif cmd == 'status':
        cmd_status()
    elif cmd == 'screenshot':
        cmd_screenshot()
    elif cmd == 'set_duration':
        secs = int(sys.argv[2]) if len(sys.argv) > 2 else 120
        r = send_command('set_duration', {'seconds': secs})
        print(json.dumps(r, indent=2))
    elif cmd == 'watch':
        cmd_watch()
    elif cmd == 'run_and_watch':
        dur = int(sys.argv[2]) if len(sys.argv) > 2 else 120
        cmd_run_and_watch(dur)
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)


if __name__ == '__main__':
    main()
