"""
gesture_detector.py — Slice gesture detection using gyroscope data

Detects "slicing" gestures (rapid wrist motion) from gyroscope angular velocity.
Also tracks combo chains when slices occur in rapid succession.

Architecture:
  - 8-frame rolling window of gyro samples
  - Slice event triggered when: peak angular velocity >= threshold AND cooldown elapsed
  - Direction classified from mean gyro components (left/right/up/down/diagonal)
  - Combo count via timestamp history within a sliding time window
"""

import math
import time
from collections import deque
from dataclasses import dataclass
from typing import Optional


# ── Configuration Constants ────────────────────────────────────────────────────

AV_THRESHOLD = 150.0        # degrees/second — threshold for "slicing" motion
COMBO_WINDOW_SECS = 1.5     # time window for counting consecutive slices as combo
SLICE_COOLDOWN = 0.25       # minimum seconds between detectable slices
WINDOW_SIZE = 8             # number of frames in rolling window (~80ms at 100 Hz)


# ── Data Classes ───────────────────────────────────────────────────────────────

@dataclass
class SliceEvent:
    """Represents one detected slice gesture."""
    direction: str          # "left"|"right"|"up"|"down"|"diagonal_ul"|"diagonal_ur"|"diagonal_dl"|"diagonal_dr"
    speed_norm: float       # 0..1 normalized speed (peak AV / (threshold × 3))
    av_magnitude: float     # raw peak angular velocity magnitude (°/s) during the gesture
    timestamp: float        # monotonic time of event


# ── Detector Class ─────────────────────────────────────────────────────────────

class SliceDetector:
    """
    Detects slice gestures from gyroscope angular velocity.

    Rolling 8-frame window fires a SliceEvent when:
      1. Peak angular velocity (over all 8 frames) >= AV_THRESHOLD
      2. Cooldown has elapsed since the last slice
      3. On each frame until cooldown expires
    """

    def __init__(self):
        """Initialize detector with empty window and history."""
        # Rolling window: deque of (gx, gy, gz, av_mag, timestamp)
        self._window: deque = deque(maxlen=WINDOW_SIZE)

        # Cooldown tracking
        self._last_slice_time: float = 0.0

        # Combo tracking: deque of slice timestamps within combo window
        self._slice_history: deque = deque()

    def update(self, gx: float, gy: float, gz: float,
               t: Optional[float] = None) -> Optional[SliceEvent]:
        """
        Process one frame of gyro data.

        Args:
            gx, gy, gz: gyroscope values in degrees/second
            t: timestamp (monotonic); uses time.monotonic() if None

        Returns:
            SliceEvent if a slice is detected, else None
        """
        if t is None:
            t = time.monotonic()

        # Compute angular velocity magnitude
        av_mag = math.sqrt(gx*gx + gy*gy + gz*gz)

        # Push to rolling window
        self._window.append((gx, gy, gz, av_mag, t))

        # Need a full window to detect
        if len(self._window) < WINDOW_SIZE:
            return None

        # Check cooldown: must wait before next slice event
        if t - self._last_slice_time < SLICE_COOLDOWN:
            return None

        # Find peak AV magnitude in the window
        peak_av = max(frame[3] for frame in self._window)

        # Check threshold
        if peak_av < AV_THRESHOLD:
            return None

        # ── Detect slice ────────────────────────────────────────────────────
        # Compute mean gyro components over the window
        mean_gx = sum(frame[0] for frame in self._window) / WINDOW_SIZE
        mean_gy = sum(frame[1] for frame in self._window) / WINDOW_SIZE
        mean_gz = sum(frame[2] for frame in self._window) / WINDOW_SIZE

        # Classify direction
        direction = self._classify_direction(mean_gx, mean_gy, mean_gz)

        # Normalize speed: 0 at threshold, 1 at (threshold × 3)
        speed_norm = min(1.0, max(0.0, (peak_av - AV_THRESHOLD) / (AV_THRESHOLD * 2)))

        # Update cooldown and combo
        self._last_slice_time = t
        self._slice_history.append(t)

        # Prune old combo history
        cutoff = t - COMBO_WINDOW_SECS
        while self._slice_history and self._slice_history[0] < cutoff:
            self._slice_history.popleft()

        return SliceEvent(
            direction=direction,
            speed_norm=speed_norm,
            av_magnitude=peak_av,
            timestamp=t,
        )

    def _classify_direction(self, mean_gx: float, mean_gy: float, mean_gz: float) -> str:
        """
        Classify slice direction from mean gyro components.

        gz controls yaw (horizontal):
          gz > 0  → rightward wrist rotation
          gz < 0  → leftward

        gy controls pitch (vertical):
          gy > 0  → upward wrist pitch (palm facing you)
          gy < 0  → downward (palm away)

        gx controls roll (twist) — less relevant for slicing direction.

        Returns one of: "left", "right", "up", "down",
                        "diagonal_ul", "diagonal_ur", "diagonal_dl", "diagonal_dr"
        """
        abs_gz = abs(mean_gz)
        abs_gy = abs(mean_gy)

        # Threshold for "primary" axis dominance (1.5x ratio)
        AXIS_RATIO = 1.5

        if abs_gz > abs_gy * AXIS_RATIO:
            # Horizontal dominant
            return "right" if mean_gz > 0 else "left"
        elif abs_gy > abs_gz * AXIS_RATIO:
            # Vertical dominant
            return "up" if mean_gy < 0 else "down"
        else:
            # Mixed diagonal — combine both axes
            gz_dir = "r" if mean_gz > 0 else "l"
            gy_dir = "u" if mean_gy < 0 else "d"
            return f"diagonal_{gy_dir}{gz_dir}"

    @property
    def combo_count(self) -> int:
        """
        Number of slices detected within the current combo window.

        Prunes entries older than COMBO_WINDOW_SECS before returning count.
        """
        now = time.monotonic()
        cutoff = now - COMBO_WINDOW_SECS

        # Prune old entries
        while self._slice_history and self._slice_history[0] < cutoff:
            self._slice_history.popleft()

        return len(self._slice_history)
