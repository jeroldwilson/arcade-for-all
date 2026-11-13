"""
gestures/types.py — Core gesture types shared by the engine, detectors and games.

See docs/v1.0-raodmap.md §6.1.  These are the only types a game needs to know:

    for e in gesture_src.poll():          # drain every event since last frame
        if e.gesture is Gesture.FLICK_UP: launch_ball()
    tilt = gesture_src.signals().tilt_x   # -1..1 continuous
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import List

try:  # Python 3.8+
    from typing import Protocol
except ImportError:  # pragma: no cover
    Protocol = object  # type: ignore


class Gesture(Enum):
    # Continuous signals (read via signals(), never emitted as events)
    TILT = auto()
    POINTER = auto()
    # Accessible gestures (default in ASTRA)
    HOLD_LEFT = auto()
    HOLD_RIGHT = auto()
    HOLD_UP = auto()
    HOLD_DOWN = auto()
    DWELL = auto()
    ANY_MOVE = auto()
    STILL = auto()
    # Standard gestures
    FLICK_UP = auto()
    FLICK_DOWN = auto()
    FLICK_LEFT = auto()
    FLICK_RIGHT = auto()
    SLICE = auto()
    TWIST_CW = auto()
    TWIST_CCW = auto()
    SHAKE = auto()


@dataclass(frozen=True)
class GestureEvent:
    gesture: Gesture
    strength: float = 1.0      # 0..1
    confidence: float = 1.0    # 1.0 for rules, model proba for ML
    direction: str = ""        # e.g. slice direction
    source: str = "rule"       # "rule" | "ml"
    t: float = 0.0             # sample timestamp (time.monotonic domain)
    detector: str = ""         # name of the detector that produced it


@dataclass(frozen=True)
class Frame:
    """One processed sample produced by the Frontend (see shared/frontend.py)."""
    t: float
    dt: float                                  # smoothed sample period (s)
    # Orientation relative to the child's neutral pose: q_rel = q_base⁻¹ ⊗ q
    qw: float = 1.0
    qx: float = 0.0
    qy: float = 0.0
    qz: float = 0.0
    # Relative angles (degrees).  roll/pitch are gravity-referenced (yaw-immune);
    # yaw is extracted from q_rel and drifts slowly in IMUPlus / 6-axis mode.
    roll: float = 0.0
    pitch: float = 0.0
    yaw: float = 0.0
    # Gyroscope (°/s), sensor frame
    gx: float = 0.0
    gy: float = 0.0
    gz: float = 0.0
    # Linear acceleration (g), gravity removed
    lin_ax: float = 0.0
    lin_ay: float = 0.0
    lin_az: float = 0.0
    # Gravity-based tilt in g-units relative to neutral (3 Hz Butterworth).
    # Same units/sign as the legacy `smooth_ax - cal_ax` tilt.
    tilt_gx: float = 0.0
    tilt_gy: float = 0.0
    # Tilt normalised by the child's per-side range of motion, clamped to -1..1
    tilt_x: float = 0.0
    tilt_y: float = 0.0
    av_magnitude: float = 0.0                  # |ω| (°/s)
    calibrated: bool = False


@dataclass(frozen=True)
class Signals:
    """Continuous control signals published every sample."""
    tilt_x: float = 0.0        # -1..1, ROM-normalised, + = right
    tilt_y: float = 0.0        # -1..1, ROM-normalised, + = back/down
    pointer_x: float = 0.5     # 0..1 screen-space pointer (orientation-mapped)
    pointer_y: float = 0.5
    roll: float = 0.0          # relative degrees
    pitch: float = 0.0
    gx: float = 0.0            # angular velocity (°/s)
    gy: float = 0.0
    gz: float = 0.0
    hold_progress: float = 0.0  # 0..1 while a hold is arming
    hold_direction: str = ""
    calibrated: bool = False


class Detector(Protocol):
    name: str

    def update(self, f: Frame) -> List[GestureEvent]: ...

    def reset(self) -> None: ...

