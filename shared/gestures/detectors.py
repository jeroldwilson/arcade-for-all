"""
gestures/detectors.py — Standard rule-based detector plug-ins (roadmap §6, Phase 4).

Each detector is a tiny state machine:  Frame in → list[GestureEvent] out.
No threads, no pygame, no wall-clock: all timing uses the frame timestamp,
so behaviour is identical live and on replay.
"""

from __future__ import annotations

import math
from collections import deque
from typing import List

from shared.gesture_detector import SliceDetector
from shared.gestures.types import Frame, Gesture, GestureEvent

# Sign of gy for an UPWARD flick / slice.  Matches SliceDetector ("up" when
# mean gy < 0) and the legacy flick-to-steer mapping.  Verify with replay data
# (tests/replay.py) if the sensor is mounted differently.
FLICK_UP_GY_SIGN = -1.0


def _windowed_peak(window: deque, now: float, span: float) -> float:
    """Drop entries older than `span` and return the signed value with largest |v|."""
    while window and window[0][0] < now - span - 1e-9:
        window.popleft()
    return max((v for _, v in window), key=abs, default=0.0)


class FlickDetector:
    """Signed-peak flick on the pitch gyro (gy) → FLICK_UP / FLICK_DOWN (§7.10).

    The cooldown is shared by both directions, so the rebound after a
    downward jerk cannot sneak through as an upward flick.
    """

    def __init__(self, threshold: float = 200.0, window_s: float = 0.06,
                 cooldown: float = 0.4, name: str = "flick"):
        self.name = name
        self.threshold = threshold
        self.window_s = window_s
        self.cooldown = cooldown
        self.reset()

    def reset(self) -> None:
        self._win: deque = deque()
        self._last = -1e9

    def update(self, f: Frame) -> List[GestureEvent]:
        self._win.append((f.t, f.gy))
        peak = _windowed_peak(self._win, f.t, self.window_s)
        if abs(peak) <= self.threshold or f.t - self._last <= self.cooldown:
            return []
        self._last = f.t
        up = peak * FLICK_UP_GY_SIGN > 0
        strength = min(1.0, (abs(peak) - self.threshold) / self.threshold)
        return [GestureEvent(Gesture.FLICK_UP if up else Gesture.FLICK_DOWN,
                             strength=strength, t=f.t, detector=self.name)]


class SteerDetector:
    """Four-way flick-to-steer: gx → left/right first, else gy → up/down."""

    def __init__(self, threshold: float = 160.0, window_s: float = 0.07,
                 cooldown: float = 0.5, name: str = "steer"):
        self.name = name
        self.threshold = threshold
        self.window_s = window_s
        self.cooldown = cooldown
        self.reset()

    def reset(self) -> None:
        self._wx: deque = deque()
        self._wy: deque = deque()
        self._last = -1e9

    def update(self, f: Frame) -> List[GestureEvent]:
        self._wx.append((f.t, f.gx))
        self._wy.append((f.t, f.gy))
        px = _windowed_peak(self._wx, f.t, self.window_s)
        py = _windowed_peak(self._wy, f.t, self.window_s)
        if f.t - self._last <= self.cooldown:
            return []
        g = None
        if abs(px) > self.threshold:
            g = Gesture.FLICK_RIGHT if px > 0 else Gesture.FLICK_LEFT
        elif abs(py) > self.threshold:
            g = Gesture.FLICK_UP if py * FLICK_UP_GY_SIGN > 0 else Gesture.FLICK_DOWN
        if g is None:
            return []
        self._last = f.t
        return [GestureEvent(g, t=f.t, detector=self.name)]


class TwistDetector:
    """Rising-edge twist events on smoothed gz with hysteresis."""

    def __init__(self, dead_zone: float = 30.0, tau_s: float = 0.05,
                 release_ratio: float = 0.7, name: str = "twist"):
        self.name = name
        self.dead_zone = dead_zone
        self.tau_s = tau_s
        self.release_ratio = release_ratio
        self.reset()

    def reset(self) -> None:
        self._gz = 0.0
        self._active = False

    def update(self, f: Frame) -> List[GestureEvent]:
        if self.dead_zone >= 900:          # ASTRA disables spin with 999
            return []
        k = 1.0 - math.exp(-f.dt / self.tau_s)
        self._gz += k * (f.gz - self._gz)
        mag = abs(self._gz)
        if not self._active and mag > self.dead_zone:
            self._active = True
            strength = min(1.0, (mag - self.dead_zone) / 200.0)
            g = Gesture.TWIST_CW if self._gz > 0 else Gesture.TWIST_CCW
            return [GestureEvent(g, strength=strength, t=f.t, detector=self.name)]
        if self._active and mag < self.dead_zone * self.release_ratio:
            self._active = False
        return []


class SliceAdapter:
    """Wraps the existing SliceDetector as a plug-in."""

    def __init__(self, name: str = "slice"):
        self.name = name
        self.detector = SliceDetector()

    def reset(self) -> None:
        self.detector = SliceDetector()

    def update(self, f: Frame) -> List[GestureEvent]:
        ev = self.detector.update(f.gx, f.gy, f.gz, t=f.t)
        if ev is None:
            return []
        return [GestureEvent(Gesture.SLICE, strength=ev.speed_norm, direction=ev.direction,
                             t=f.t, detector=self.name)]

    def combo_count_at(self, t: float) -> int:
        return self.detector.combo_count_at(t)

