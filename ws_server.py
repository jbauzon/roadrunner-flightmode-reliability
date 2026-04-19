# SPDX-FileCopyrightText: 2026 Anduril Industries, Inc.
# SPDX-License-Identifier: Apache-2.0
"""Backwards-compatible entry point for start.bat and existing muscle memory.

All code lives in :mod:`rr_test.server`.  This shim exists so that:

  * `python ws_server.py --sitl` keeps working
  * `start.bat` keeps working
  * `python -m rr_test.server --sitl` (new canonical entry) also works

"""
from __future__ import annotations

import asyncio
import os
import sys

# Ensure rr_test is importable when running from a clone without
# `pip install -e .`.  After install, sys.path already contains the package.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# SITL env var must be set BEFORE any rr_test.execution import (it controls
# whether connect_to_vehicle allows loopback addresses).  The server module
# does this too but we do it here too for defense in depth.
if "--sitl" in sys.argv:
    os.environ["RR_SITL_MODE"] = "1"

from rr_test.server.server import main

if __name__ == "__main__":
    asyncio.run(main())
