"""
filters.py — Adaptive 1€ (One Euro) Filter for tremor-robust, low-latency smoothing.

Pure Python, timestamp-driven (no wall-clock calls), fully replay-deterministic.
Reference: Casiez, Roussel, Vogel (CHI 2012) — "1€ Filter: A Simple Speed-based
Low-pass Filter for Noisy Input in Interactive Systems".
"""

from __future__ import annotations

import math
from typing import Optional, Tuple


def _smoothing_factor(dt: float, cutoff: float) -> float:
    r = 2.0 * math.pi * cutoff * dt
    return r / (r + 1.0)


class OneEuroFilter:
    """1D One Euro Filter: heavy smoothing at rest, low lag during fast reaches."""

    def __init__(
        self,
        min_cutoff: float = 1.2,
        beta: float = 0.05,
        d_cutoff: float = 1.0,
    ):
        self.min_cutoff = float(min_cutoff)
        self.beta = float(beta)
        self.d_cutoff = float(d_cutoff)
        self.reset()

    def reset(self) -> None:
        self._x_prev: Optional[float] = None
        self._dx_prev: float = 0.0
        self._t_prev: Optional[float] = None

    def update(self, x: float, t: float) -> float:
        if self._t_prev is None or self._x_prev is None:
            self._x_prev = float(x)
            self._dx_prev = 0.0
            self._t_prev = float(t)
            return float(x)

        dt = max(1e-4, float(t) - self._t_prev)
        self._t_prev = float(t)

        # Estimate derivative and smooth it
        dx = (float(x) - self._x_prev) / dt
        a_d = _smoothing_factor(dt, self.d_cutoff)
        dx_hat = a_d * dx + (1.0 - a_d) * self._dx_prev
        self._dx_prev = dx_hat

        # Adapt cutoff frequency based on signal speed
        cutoff = self.min_cutoff + self.beta * abs(dx_hat)
        a = _smoothing_factor(dt, cutoff)
        x_hat = a * float(x) + (1.0 - a) * self._x_prev
        self._x_prev = x_hat
        return x_hat


class OneEuroFilter3D:
    """3-axis One Euro Filter for 3D hand position (pos_x, pos_y, pos_z)."""

    def __init__(
        self,
        min_cutoff: float = 1.2,
        beta: float = 0.05,
        d_cutoff: float = 1.0,
    ):
        self._fx = OneEuroFilter(min_cutoff=min_cutoff, beta=beta, d_cutoff=d_cutoff)
        self._fy = OneEuroFilter(min_cutoff=min_cutoff, beta=beta, d_cutoff=d_cutoff)
        self._fz = OneEuroFilter(min_cutoff=min_cutoff, beta=beta, d_cutoff=d_cutoff)

    def reset(self) -> None:
        self._fx.reset()
        self._fy.reset()
        self._fz.reset()

    def update(self, x: float, y: float, z: float, t: float) -> Tuple[float, float, float]:
        return (
            self._fx.update(x, t),
            self._fy.update(y, t),
            self._fz.update(z, t),
        )
