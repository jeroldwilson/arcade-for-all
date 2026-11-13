"""
gestures/accessible.py — Spasm-robust accessible detectors (roadmap §7.3–7.5, Phase 5).

  HoldDetector    tilt beyond T_ON for hold_time → HOLD_*  (Schmitt-trigger hysteresis)
  DwellDetector   pointer stays inside a small circle (off-centre) → DWELL
  AnyMoveDetector sustained movement → ANY_MOVE  (single-switch input)
  StillDetector   still for N s after moving → STILL
  SpasmGate       holds discrete events briefly and drops those produced by
                  short, jerky bursts (likely involuntary)

All timing uses frame timestamps (replayable).  Thresholds are in the units
documented per class; per-child values come from ChildProfile (§7.6).
"""

from __future__ import annotations

import math
from typing import Iterable, List, Sequence

from shared.gestures.types import Frame, Gesture, GestureEvent


class HoldDetector:
    """IDLE → ARMING (|tilt| > t_on) → FIRED (held hold_time) → IDLE (|tilt| < t_off).

    axis="x" uses Frame.tilt_x (→ HOLD_LEFT/RIGHT); axis="y" uses tilt_y
    (+ = wrist back → HOLD_DOWN, − = forward → HOLD_UP).  Units: ROM-normalised
    tilt, −1..1.
    """

    IDLE, ARMING, FIRED = "IDLE", "ARMING", "FIRED"

    def __init__(self, axis: str = "x", t_on: float = 0.25, t_off: float = 0.15,
                 hold_time: float = 0.6, name: str = ""):
        self.axis = axis
        self.t_on = t_on
        self.t_off = min(t_off, t_on)
        self.hold_time = hold_time
        self.name = name or f"hold_{axis}"
        self.reset()

    def reset(self) -> None:
        self.state = self.IDLE
        self._start = 0.0
        self._dir = 0
        self.progress = 0.0

    @property
    def arming(self) -> bool:
        return self.state == self.ARMING

    @property
    def direction(self) -> str:
        if self._dir == 0:
            return ""
        if self.axis == "x":
            return "right" if self._dir > 0 else "left"
        return "down" if self._dir > 0 else "up"

    def _gesture(self) -> Gesture:
        if self.axis == "x":
            return Gesture.HOLD_RIGHT if self._dir > 0 else Gesture.HOLD_LEFT
        return Gesture.HOLD_DOWN if self._dir > 0 else Gesture.HOLD_UP

    def update(self, f: Frame) -> List[GestureEvent]:
        if not f.calibrated:
            self.reset()
            return []
        x = f.tilt_x if self.axis == "x" else f.tilt_y
        sgn = 1 if x > 0 else -1
        if self.state == self.IDLE:
            self.progress = 0.0
            if abs(x) > self.t_on:
                self.state, self._start, self._dir = self.ARMING, f.t, sgn
        elif self.state == self.ARMING:
            if abs(x) < self.t_off or sgn != self._dir:
                self.state, self.progress, self._dir = self.IDLE, 0.0, 0
            else:
                self.progress = min(1.0, (f.t - self._start) / max(self.hold_time, 1e-6))
                if f.t - self._start >= self.hold_time:
                    self.state = self.FIRED
                    self.progress = 1.0
                    return [GestureEvent(self._gesture(), strength=min(1.0, abs(x)),
                                         t=f.t, detector=self.name)]
        elif self.state == self.FIRED:
            if abs(x) < self.t_off:
                self.state, self.progress, self._dir = self.IDLE, 0.0, 0
        return []


class DwellDetector:
    """Fires DWELL when the ROM-normalised pointer stays within `radius` of an
    anchor for `dwell_time`, while at least `min_offset` away from neutral
    (so resting at centre never fires).  Re-arms after leaving the circle."""

    def __init__(self, dwell_time: float = 1.0, radius: float = 0.12,
                 min_offset: float = 0.25, name: str = "dwell"):
        self.name = name
        self.dwell_time = dwell_time
        self.radius = radius
        self.min_offset = min_offset
        self.reset()

    def reset(self) -> None:
        self._anchor = None
        self._start = 0.0
        self._fired = False
        self.progress = 0.0

    def update(self, f: Frame) -> List[GestureEvent]:
        if not f.calibrated:
            self.reset()
            return []
        px, py = f.tilt_x, f.tilt_y
        if math.hypot(px, py) < self.min_offset:
            self.reset()
            return []
        if self._anchor is None or math.hypot(px - self._anchor[0], py - self._anchor[1]) > self.radius:
            self._anchor, self._start, self._fired = (px, py), f.t, False
            self.progress = 0.0
            return []
        if self._fired:
            return []
        self.progress = min(1.0, (f.t - self._start) / max(self.dwell_time, 1e-6))
        if f.t - self._start >= self.dwell_time:
            self._fired = True
            ax, ay = self._anchor
            if abs(ax) >= abs(ay):
                d = "right" if ax > 0 else "left"
            else:
                d = "down" if ay > 0 else "up"
            return [GestureEvent(Gesture.DWELL, strength=min(1.0, math.hypot(ax, ay)),
                                 direction=d, t=f.t, detector=self.name)]
        return []


class AnyMoveDetector:
    """Single-switch trigger: |ω| above `threshold` (°/s) for `min_duration` s."""

    def __init__(self, threshold: float = 40.0, min_duration: float = 0.2,
                 cooldown: float = 1.0, name: str = "any_move"):
        self.name = name
        self.threshold = threshold
        self.min_duration = min_duration
        self.cooldown = cooldown
        self.reset()

    def reset(self) -> None:
        self._start = None
        self._fired = False
        self._last = -1e9

    def update(self, f: Frame) -> List[GestureEvent]:
        moving = f.av_magnitude > self.threshold
        if not moving:
            if f.av_magnitude < 0.6 * self.threshold:
                self._start, self._fired = None, False
            return []
        if self._start is None:
            self._start = f.t
        if (not self._fired and f.t - self._start >= self.min_duration
                and f.t - self._last > self.cooldown):
            self._fired = True
            self._last = f.t
            return [GestureEvent(Gesture.ANY_MOVE,
                                 strength=min(1.0, f.av_magnitude / (4 * self.threshold)),
                                 t=f.t, detector=self.name)]
        return []


class StillDetector:
    """STILL after `still_time` s with |ω| < threshold — only after real movement."""

    def __init__(self, threshold: float = 10.0, still_time: float = 2.0,
                 name: str = "still"):
        self.name = name
        self.threshold = threshold
        self.still_time = still_time
        self.reset()

    def reset(self) -> None:
        self._moved = False
        self._start = None

    def update(self, f: Frame) -> List[GestureEvent]:
        if f.av_magnitude > 3 * self.threshold:
            self._moved, self._start = True, None
            return []
        if f.av_magnitude >= self.threshold or not self._moved:
            self._start = None
            return []
        if self._start is None:
            self._start = f.t
        if f.t - self._start >= self.still_time:
            self._moved, self._start = False, None
            return [GestureEvent(Gesture.STILL, t=f.t, detector=self.name)]
        return []


# ── Spasm rejection gate ──────────────────────────────────────────────────────

_SUSTAINED = {Gesture.HOLD_LEFT, Gesture.HOLD_RIGHT, Gesture.HOLD_UP, Gesture.HOLD_DOWN,
              Gesture.DWELL, Gesture.STILL}


class SpasmGate:
    """Rule-based involuntary-movement filter (§7.5).

    Intentional movement is smooth and sustained; spasms are sudden and short.
    Each discrete event is held for `min_burst_s` so the whole motion burst can
    be seen, then dropped if:
      • the burst of |ω| > motion_threshold containing the event lasted less
        than min_burst_s  (not applied to sustained gestures like HOLD/DWELL), or
      • peak linear jerk (g/s) or angular acceleration (°/s²) in the window
        exceeds its threshold.

    NOTE: quick flicks are ~60–100 ms bursts and *will* be rejected — enable
    the gate together with hold / any-move style inputs (ASTRA profiles).
    """

    def __init__(self, min_burst_s: float = 0.15, motion_threshold: float = 60.0,
                 jerk_threshold: float = 40.0, ang_accel_threshold: float = 30000.0,
                 lookback_s: float = 0.5):
        self.min_burst_s = min_burst_s
        self.motion_threshold = motion_threshold
        self.jerk_threshold = jerk_threshold
        self.ang_accel_threshold = ang_accel_threshold
        self.lookback_s = lookback_s
        self._pending: List[GestureEvent] = []
        self.rejected: int = 0

    def reset(self) -> None:
        self._pending.clear()

    def filter(self, events: Iterable[GestureEvent], buffer: Sequence[Frame],
               now: float) -> List[GestureEvent]:
        self._pending.extend(events)
        out, keep = [], []
        for e in self._pending:
            sustained = e.gesture in _SUSTAINED
            if not sustained and now - e.t < self.min_burst_s:
                keep.append(e)
                continue
            if self._is_involuntary(e, buffer, check_duration=not sustained):
                self.rejected += 1
            else:
                out.append(e)
        self._pending = keep
        return out

    def _is_involuntary(self, e: GestureEvent, buffer: Sequence[Frame],
                        check_duration: bool) -> bool:
        lo, hi = e.t - self.lookback_s, e.t + self.min_burst_s
        win = [f for f in buffer if lo <= f.t <= hi]
        if len(win) < 2:
            return False
        # Peak jerk / angular acceleration
        for a, b in zip(win, win[1:]):
            dt = max(b.t - a.t, 1e-3)
            jerk = math.sqrt((b.lin_ax - a.lin_ax) ** 2 + (b.lin_ay - a.lin_ay) ** 2
                             + (b.lin_az - a.lin_az) ** 2) / dt
            ang = abs(b.av_magnitude - a.av_magnitude) / dt
            if jerk > self.jerk_threshold or ang > self.ang_accel_threshold:
                return True
        if not check_duration:
            return False
        # Contiguous burst containing the event time
        idx = min(range(len(win)), key=lambda i: abs(win[i].t - e.t))
        if win[idx].av_magnitude <= self.motion_threshold:
            return False  # event not driven by gyro burst (e.g. tilt) — keep
        i = j = idx
        while i > 0 and win[i - 1].av_magnitude > self.motion_threshold:
            i -= 1
        while j < len(win) - 1 and win[j + 1].av_magnitude > self.motion_threshold:
            j += 1
        duration = win[j].t - win[i].t + win[j].dt
        return duration < self.min_burst_s

