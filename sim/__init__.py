# -*- coding: utf-8 -*-
"""
sim -- Pandion vehicle SITL (Software-In-The-Loop) package.

Public API:
    PandionVehicleSim  - Full-fidelity vehicle simulator
    SimFleet           - Multi-vehicle fleet management
    MockDAQController  - Drop-in DAQ replacement for sim mode

Usage:
    from sim.vehicle import PandionVehicleSim
    from sim.fleet import SimFleet
    from sim.mock_daq import MockDAQController
    from sim.config.scenarios import HEALTHY_FAST, ELEVON_FAIL
"""
from .vehicle import PandionVehicleSim
from .fleet import SimFleet
from .mock_daq import MockDAQController
