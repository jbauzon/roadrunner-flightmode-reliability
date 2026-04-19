# SPDX-FileCopyrightText: 2026 Anduril Industries, Inc.
# SPDX-License-Identifier: Apache-2.0
"""pytest conftest — add project root to sys.path for imports.

When the ``rr_test`` package has been installed with ``pip install -e .``
this is a no-op (the package is already importable).  When developers
run tests directly against a fresh clone without installing, this makes
``from rr_test import ...`` work.

Lets each test file import cleanly::

    from rr_test.vehicle.connection import UUT

instead of the former boilerplate::

    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, ROOT)
    from vehicle.connection import UUT
"""
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
