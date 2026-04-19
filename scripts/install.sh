#!/usr/bin/env bash
# Fresh-computer installer for Roadrunner Flight Mode IBIT Test System.
# Works on Linux and macOS (SITL only — NI-DAQmx is Windows only).

set -e
cd "$(dirname "$0")/.."

echo
echo "============================================================"
echo "  Roadrunner Flight Test - Installer"
echo "============================================================"
echo

# --- Check Python -----------------------------------------------------------
if ! command -v python3 >/dev/null 2>&1; then
    echo "[ERROR] python3 not found. Install Python 3.11 or newer."
    exit 1
fi
PY_VER=$(python3 --version 2>&1 | awk '{print $2}')
echo "[OK]    Python $PY_VER detected"

# --- Create venv ------------------------------------------------------------
if [ ! -d .venv ]; then
    echo "[INFO]  Creating virtual environment .venv ..."
    python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

# --- Install Python deps ----------------------------------------------------
echo "[INFO]  Installing Python dependencies ..."
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -e .
echo "[OK]    Python dependencies installed"

# --- Check Node.js + build frontend -----------------------------------------
if ! command -v node >/dev/null 2>&1; then
    echo "[WARN]  Node.js not found. Install from https://nodejs.org/"
    echo "        The web frontend cannot be built without Node."
    exit 1
fi
if [ ! -f web/dist/index.html ]; then
    echo "[INFO]  Building web frontend ..."
    (cd web && npm install --silent && npm run build)
fi
echo "[OK]    Web frontend built (web/dist/)"

echo
echo "============================================================"
echo "  Installation complete."
echo
echo "  Run:  python ws_server.py --sitl   (simulator, no hardware)"
echo "  Note: Real hardware support (NI-DAQmx) is Windows only."
echo "============================================================"
