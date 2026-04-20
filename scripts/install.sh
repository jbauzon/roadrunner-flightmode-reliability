#!/usr/bin/env bash
# One-time installer (Linux / macOS, SITL only — NI-DAQmx is Windows only).
# No virtualenv — deps go into user Python via pip --user.

set -e
cd "$(dirname "$0")/.."

echo
echo "============================================================"
echo "  Roadrunner Flight Test - Installer"
echo "============================================================"
echo

if ! command -v python3 >/dev/null 2>&1; then
    echo "[ERROR] python3 not found. Install Python 3.11 or newer."
    exit 1
fi
PY_VER=$(python3 --version 2>&1 | awk '{print $2}')
echo "[OK]    Python $PY_VER detected"

echo "[INFO]  Installing Roadrunner test package and dependencies..."
python3 -m pip install --upgrade pip
python3 -m pip install -e .
echo "[OK]    Python package installed"

python3 -c "import rr_test, pymavlink, websockets" 2>&1 || {
    echo "[ERROR] Import check failed after install."
    exit 1
}
echo "[OK]    Core imports verified"

if ! command -v node >/dev/null 2>&1; then
    echo "[WARN]  Node.js not found. Install from https://nodejs.org/"
    exit 1
fi
if [ ! -f web/dist/index.html ]; then
    echo "[INFO]  Building web frontend..."
    (cd web && npm install && npm run build)
fi
echo "[OK]    Web frontend built (web/dist/)"

echo
echo "============================================================"
echo "  Installation complete."
echo "  Run:  python3 ws_server.py --sitl"
echo "============================================================"
