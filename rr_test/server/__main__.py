# SPDX-FileCopyrightText: 2026 Anduril Industries, Inc.
# SPDX-License-Identifier: Apache-2.0
"""Module entry: ``python -m rr_test.server [--sitl]``."""
from __future__ import annotations

import asyncio
import os
import sys

# SITL env var must be set BEFORE importing rr_test.execution.*
if "--sitl" in sys.argv:
    os.environ["RR_SITL_MODE"] = "1"

from rr_test.server.server import main

if __name__ == "__main__":
    asyncio.run(main())
