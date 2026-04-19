# -*- coding: utf-8 -*-
"""
sim.clock -- Simulation clock for deterministic replay.

Provides a monotonic tick-based clock that replaces time.time() and
time.sleep() in deterministic mode, ensuring byte-identical telemetry
across runs. In real-time mode, delegates to actual system calls.

Usage:
    from sim.clock import SimClock
    clock = SimClock(deterministic=True, seed=42)
    clock.time()   # returns monotonic tick time
    clock.sleep(0.01)  # advances tick counter
    clock.random()  # seeded random instance
"""
from __future__ import annotations

import time
import random as _random
from typing import Optional


class SimClock:
    """Simulation clock with deterministic and real-time modes."""

    def __init__(self, deterministic: bool = False, seed: int = 42,
                 tick_rate: float = 100.0):
        self.deterministic = deterministic
        self._tick = 0
        self._tick_dt = 1.0 / tick_rate
        self._start = time.time()
        self.random = _random.Random(seed) if deterministic else _random.Random()

    def time(self) -> float:
        """Current time (monotonic ticks or wall-clock)."""
        if self.deterministic:
            return self._tick * self._tick_dt
        return time.time()

    def sleep(self, seconds: float) -> None:
        """Sleep (advance tick counter or real sleep)."""
        if self.deterministic:
            ticks = max(1, int(seconds / self._tick_dt))
            self._tick += ticks
        else:
            time.sleep(seconds)

    def gauss(self, mu: float, sigma: float) -> float:
        """Gaussian random (seeded or system)."""
        return self.random.gauss(mu, sigma)

    def uniform(self, a: float, b: float) -> float:
        """Uniform random (seeded or system)."""
        return self.random.uniform(a, b)

    def randint(self, a: int, b: int) -> int:
        """Random integer (seeded or system)."""
        return self.random.randint(a, b)

    def chance(self, probability: float) -> bool:
        """Return True with given probability."""
        return self.random.random() < probability

    def reset(self, seed: Optional[int] = None) -> None:
        """Reset clock and RNG state."""
        self._tick = 0
        self._start = time.time()
        if seed is not None:
            self.random = _random.Random(seed)
