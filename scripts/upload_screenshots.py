#!/usr/bin/env python3
"""
upload_screenshots.py — Upload docs/images/*.png to Confluence and update
the page body to include them inline.

Usage:
    python scripts/upload_screenshots.py

Requires CONFLUENCE_API_TOKEN in environment (or ~/.env).
"""
import os
import sys
import json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMG_DIR = os.path.join(ROOT, "docs", "images")
PAGE_ID = "558927073"
BASE_URL = "https://confluence.anduril.dev/rest/api/content"

# Load token
for env_file in [os.path.expanduser("~/.env"), os.path.join(ROOT, ".env")]:
    if os.path.isfile(env_file):
        with open(env_file) as f:
            for line in f:
                if line.strip() and "=" in line and not line.startswith("#"):
                    k, v = line.strip().split("=", 1)
                    os.environ.setdefault(k, v)

TOKEN = os.environ.get("CONFLUENCE_API_TOKEN")
if not TOKEN:
    print("ERROR: CONFLUENCE_API_TOKEN not found in environment or ~/.env")
    sys.exit(1)

try:
    import requests
except ImportError:
    print("ERROR: 'requests' package required. pip install requests")
    sys.exit(1)

HEADERS = {"Authorization": f"Bearer {TOKEN}"}

# List PNGs
pngs = sorted(f for f in os.listdir(IMG_DIR) if f.endswith(".png"))
if not pngs:
    print(f"No PNGs found in {IMG_DIR}/")
    sys.exit(1)

print(f"Found {len(pngs)} screenshots in {IMG_DIR}/")

# Upload each as attachment
for f in pngs:
    path = os.path.join(IMG_DIR, f)
    size_kb = os.path.getsize(path) / 1024
    print(f"  Uploading {f} ({size_kb:.0f} KB)...", end=" ")

    with open(path, "rb") as fh:
        resp = requests.post(
            f"{BASE_URL}/{PAGE_ID}/child/attachment",
            headers={**HEADERS, "X-Atlassian-Token": "nocheck"},
            files={"file": (f, fh, "image/png")},
        )

    if resp.status_code in (200, 201):
        print("OK")
    elif resp.status_code == 409:
        # Already exists — update it
        resp2 = requests.put(
            f"{BASE_URL}/{PAGE_ID}/child/attachment",
            headers={**HEADERS, "X-Atlassian-Token": "nocheck"},
            files={"file": (f, open(path, "rb"), "image/png")},
        )
        print(f"updated ({resp2.status_code})")
    else:
        print(f"FAILED ({resp.status_code}): {resp.text[:100]}")

print()
print("Done. Screenshots are now attached to the Confluence page.")
print(f"URL: https://confluence.anduril.dev/spaces/ROAD/pages/{PAGE_ID}")
print()
print("To embed them in the page body, edit the page in Confluence and")
print("insert the attachments as images where appropriate.")
