#!/usr/bin/env python3
"""
analyze_screenshots.py — Post-test screenshot analyzer.

Reads screenshots from ./screenshots/, displays metadata, and
generates a summary report. Can be used after gui_test.py runs.

Usage:
    python analyze_screenshots.py
    python analyze_screenshots.py --dir screenshots
    python analyze_screenshots.py --latest 5   # show last 5 only
"""

import os
import sys
import json
import argparse
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DIR = os.path.join(ROOT, "screenshots")


def analyze(screenshot_dir, latest=None):
    """Analyze screenshots in directory."""

    if not os.path.isdir(screenshot_dir):
        print(f"Directory not found: {screenshot_dir}")
        return

    # Find all PNGs
    pngs = sorted([
        f for f in os.listdir(screenshot_dir) if f.endswith(".png")
    ])

    if not pngs:
        print("No screenshots found.")
        return

    if latest:
        pngs = pngs[-latest:]

    print(f"{'='*70}")
    print(f"  SCREENSHOT ANALYSIS — {len(pngs)} image(s)")
    print(f"  Directory: {screenshot_dir}")
    print(f"{'='*70}")
    print()

    total_size = 0
    for i, fname in enumerate(pngs, 1):
        fpath = os.path.join(screenshot_dir, fname)
        size_kb = os.path.getsize(fpath) / 1024
        total_size += size_kb

        # Parse timestamp and name from filename
        parts = fname.replace(".png", "").split("_", 2)
        if len(parts) >= 3:
            date_str = parts[0]
            time_str = parts[1]
            label = parts[2].replace("_", " ").title()
        else:
            date_str = ""
            time_str = ""
            label = fname

        print(f"  [{i:2d}] {fname}")
        print(f"       Label:  {label}")
        print(f"       Size:   {size_kb:.0f} KB")
        print()

    print(f"  Total: {total_size:.0f} KB across {len(pngs)} screenshots")
    print()

    # Read test report if available
    report_path = os.path.join(screenshot_dir, "test_report.json")
    if os.path.exists(report_path):
        with open(report_path) as f:
            report = json.load(f)

        print(f"  Test Report:")
        print(f"    Run time:     {report.get('test_run', 'unknown')}")
        print(f"    Screenshots:  {report.get('total_screenshots', 0)}")
        print()

        for s in report.get("screenshots", []):
            name = s.get("name", "?")
            t    = s.get("time", "?")
            print(f"    {name:40s}  {t}")

    print()
    print(f"{'='*70}")
    print(f"  To view: open {screenshot_dir}")
    print(f"{'='*70}")

    return pngs


def main():
    parser = argparse.ArgumentParser(description="Analyze GUI test screenshots")
    parser.add_argument("--dir", default=DEFAULT_DIR, help="Screenshot directory")
    parser.add_argument("--latest", type=int, help="Show only N most recent")
    args = parser.parse_args()
    analyze(args.dir, args.latest)


if __name__ == "__main__":
    main()
