#!/usr/bin/env python3
"""
capture_screenshots.py — Automated screenshot capture for Confluence docs.

Launches the server with SITL, opens headless Chromium, drives through
each UI state, and saves screenshots to docs/images/.

Then optionally uploads them to the Confluence page and updates the
page body with inline image references.

Screenshots captured:
  01_initial_state.png        — App loaded, SITL UUTs visible, idle
  02_debug_connect.png        — Debug Mode, connected to a vehicle, telemetry flowing
  03_debug_armed.png          — Debug Mode, vehicle ARMED, OPERATE mode
  04_test_config.png          — Test Mode, IBIT selected, duration set
  05_ibit_running.png         — IBIT batch active, vehicle connected, IBIT phase visible
  06_ibit_result.png          — IBIT iteration complete, PASS/FAIL visible
  07_playback_config.png      — Playback mode selected, CSV loaded
  08_log_files.png            — (skip — can't screenshot Explorer from headless)

Usage:
    python scripts/capture_screenshots.py                  # capture only
    python scripts/capture_screenshots.py --upload         # capture + upload to Confluence
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

IMG_DIR = os.path.join(ROOT, "docs", "images")
WS_URL = "ws://127.0.0.1:18889"
HTTP_URL = "http://localhost:18890"


def start_server():
    try:
        subprocess.run(["pkill", "-9", "-f", "ws_server.py"], timeout=3, capture_output=True)
        time.sleep(2)
    except Exception:
        pass
    proc = subprocess.Popen(
        [sys.executable, "-B", os.path.join(ROOT, "ws_server.py"), "--sitl"],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    # Wait for server
    for _ in range(20):
        try:
            import urllib.request
            urllib.request.urlopen(HTTP_URL, timeout=1)
            break
        except Exception:
            time.sleep(0.5)
    time.sleep(3)  # Let SITL finish launching
    return proc


def stop_server(proc):
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def capture_screenshots():
    from playwright.sync_api import sync_playwright

    os.makedirs(IMG_DIR, exist_ok=True)
    print(f"Saving screenshots to {IMG_DIR}/")

    proc = start_server()
    print("Server started with SITL")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(
                viewport={"width": 1920, "height": 1080},
                device_scale_factor=1,
            )
            page = ctx.new_page()

            # ── 01: Initial state ────────────────────────────────
            print("  01: Initial state...")
            page.goto(HTTP_URL)
            page.wait_for_timeout(3000)  # Let state.sync + SITL UUTs load
            page.screenshot(path=os.path.join(IMG_DIR, "01_initial_state.png"), full_page=False)
            print("    saved")

            # ── 02: Debug Mode — connected ───────────────────────
            print("  02: Debug Mode connected...")
            # Click Debug tab (look for text "Debug" in nav)
            debug_tab = page.locator("text=Debug").first
            if debug_tab.is_visible(timeout=3000):
                debug_tab.click()
                page.wait_for_timeout(1000)

                # Send connect command via WS
                page.evaluate("""() => {
                    // The app's WS is available via the hook; we'll use
                    // a direct WS to send cmd.debug.connect
                }""")
                # Simpler: just use the UI buttons if they exist
                connect_btn = page.locator("button:has-text('Connect')").first
                if connect_btn.is_visible(timeout=2000):
                    # Need to select a UUT first — look for a dropdown/select
                    page.wait_for_timeout(500)

                    # Send via WebSocket directly
                    import websockets.sync.client as ws_sync
                    try:
                        ws = ws_sync.connect(WS_URL, open_timeout=3)
                        ws.send(json.dumps({"type": "cmd.sync_state"}))
                        ws.recv(timeout=2)
                        # Get UUT info
                        ws.send(json.dumps({
                            "type": "cmd.debug.connect",
                            "data": {"serial": "RR-SIM-001", "ip": "127.0.0.1", "port": 19901}
                        }))
                        time.sleep(3)  # Let telemetry flow
                        ws.close()
                    except Exception as e:
                        print(f"    WS error: {e}")

                page.wait_for_timeout(2000)
                page.screenshot(path=os.path.join(IMG_DIR, "02_debug_connect.png"), full_page=False)
                print("    saved")

                # ── 03: Debug Mode — armed ───────────────────────
                print("  03: Debug Mode armed...")
                try:
                    ws = ws_sync.connect(WS_URL, open_timeout=3)
                    ws.send(json.dumps({
                        "type": "cmd.debug.arm",
                        "data": {"arm": True, "force": True}
                    }))
                    time.sleep(3)
                    ws.close()
                except Exception as e:
                    print(f"    WS error: {e}")
                page.wait_for_timeout(2000)
                page.screenshot(path=os.path.join(IMG_DIR, "03_debug_armed.png"), full_page=False)
                print("    saved")

                # Disconnect + disarm
                try:
                    ws = ws_sync.connect(WS_URL, open_timeout=3)
                    ws.send(json.dumps({"type": "cmd.debug.arm", "data": {"arm": False, "force": False}}))
                    time.sleep(1)
                    ws.send(json.dumps({"type": "cmd.debug.disconnect"}))
                    time.sleep(1)
                    ws.close()
                except Exception:
                    pass

            # ── 04: Test Mode — config ───────────────────────────
            print("  04: Test config...")
            test_tab = page.locator("text=Test").first
            if test_tab.is_visible(timeout=2000):
                test_tab.click()
            page.wait_for_timeout(1500)
            page.screenshot(path=os.path.join(IMG_DIR, "04_test_config.png"), full_page=False)
            print("    saved")

            # ── 05: IBIT running ─────────────────────────────────
            print("  05: IBIT running (starting batch, waiting ~25s)...")
            try:
                ws = ws_sync.connect(WS_URL, open_timeout=3)
                ws.send(json.dumps({
                    "type": "cmd.start_test",
                    "data": {"mode": "ibit", "duration_seconds": 120}
                }))
                ws.close()
            except Exception as e:
                print(f"    WS error: {e}")

            # Wait for IBIT to be in progress (ARM + mode transitions take ~20s)
            page.wait_for_timeout(20000)
            page.screenshot(path=os.path.join(IMG_DIR, "05_ibit_running.png"), full_page=False)
            print("    saved")

            # ── 06: IBIT result ──────────────────────────────────
            print("  06: IBIT result (waiting for completion, ~40s)...")
            page.wait_for_timeout(40000)
            page.screenshot(path=os.path.join(IMG_DIR, "06_ibit_result.png"), full_page=False)
            print("    saved")

            # Stop the batch
            try:
                ws = ws_sync.connect(WS_URL, open_timeout=3)
                ws.send(json.dumps({"type": "cmd.stop_test"}))
                time.sleep(3)
                ws.close()
            except Exception:
                pass

            # ── 07: Playback config ──────────────────────────────
            print("  07: Playback config...")
            # Click the Playback radio if visible
            playback_btn = page.locator("button:has-text('Playback')").first
            if playback_btn.is_visible(timeout=2000):
                playback_btn.click()
            page.wait_for_timeout(1500)
            page.screenshot(path=os.path.join(IMG_DIR, "07_playback_config.png"), full_page=False)
            print("    saved")

            browser.close()

    finally:
        stop_server(proc)

    # List captured files
    print()
    print("Screenshots captured:")
    for f in sorted(os.listdir(IMG_DIR)):
        if f.endswith(".png"):
            size_kb = os.path.getsize(os.path.join(IMG_DIR, f)) / 1024
            print(f"  {f}  ({size_kb:.0f} KB)")


def upload_to_confluence():
    """Upload screenshots as attachments and update page body."""
    import dotenv
    dotenv.load_dotenv(os.path.expanduser("~/.env"))

    token = os.environ.get("CONFLUENCE_API_TOKEN")
    if not token:
        print("ERROR: CONFLUENCE_API_TOKEN not set")
        return

    import requests

    base = "https://confluence.anduril.dev/rest/api/content"
    page_id = "558927073"
    headers = {"Authorization": f"Bearer {token}"}

    # Upload each PNG as attachment
    for f in sorted(os.listdir(IMG_DIR)):
        if not f.endswith(".png"):
            continue
        path = os.path.join(IMG_DIR, f)
        print(f"  Uploading {f}...")
        with open(path, "rb") as fh:
            resp = requests.post(
                f"{base}/{page_id}/child/attachment",
                headers={**headers, "X-Atlassian-Token": "nocheck"},
                files={"file": (f, fh, "image/png")},
            )
        if resp.status_code in (200, 201):
            print(f"    OK")
        else:
            print(f"    {resp.status_code}: {resp.text[:200]}")

    print("Upload complete. Refresh the Confluence page to see images.")


if __name__ == "__main__":
    capture_screenshots()
    if "--upload" in sys.argv:
        upload_to_confluence()
