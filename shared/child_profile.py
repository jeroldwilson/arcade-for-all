"""
child_profile.py — Per-child calibration profile (roadmap §7.6, Phase 3).

Persists per-child motor parameters in `data/profiles/{username}.json` while
preserving existing keys (`username`, `created`, etc.) written by
`shared/username_screen.py`.

Calibration steps (§7.6):
  1. Rest   (10 s) → neutral quaternion q_base, resting tremor_rms_deg
  2. Reach  (3×)   → 90th-percentile ROM for left, right, up, down (degrees)
  3. Swing  (3 s)  → primary movement axis θ via 2D PCA (radians)
  4. Hold          → hold_time = 0.6 × median comfortable hold duration
  5. React         → reaction_time = median latency → cooldown = max(0.5, 1.5 × rt)

Derived thresholds:
  t_on     = max(0.15, 3 × tremor_rms_deg / rom_min_deg)   (clamped ≤ 0.65)
  t_off    = 0.6 × t_on
  cooldown = max(0.5, 1.5 × reaction_time)
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

from shared.gestures.types import Frame
from shared.quat import IDENTITY, Quat, q_average, q_normalize

PROFILES_DIR = Path(__file__).parent.parent / "data" / "profiles"

VALID_MOUNTS = ("dorsal_hand", "wrist", "head", "foot", "elbow")


def _percentile(values: Sequence[float], pct: float) -> float:
    """Linear-interpolated percentile (0..100) without requiring numpy."""
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * (pct / 100.0)
    lo = int(math.floor(k))
    hi = int(math.ceil(k))
    if lo == hi:
        return s[lo]
    return s[lo] + (k - lo) * (s[hi] - s[lo])


def _median(values: Sequence[float]) -> float:
    return _percentile(values, 50.0)


@dataclass
class ChildProfile:
    username: str = "guest"
    created: str = field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S"))
    mount_location: str = "dorsal_hand"       # dorsal_hand | wrist | head | foot | elbow
    q_base: Tuple[float, float, float, float] = IDENTITY
    # Per-side range of motion (degrees, >= 5°)
    rom_left_deg: float = 30.0
    rom_right_deg: float = 30.0
    rom_up_deg: float = 30.0
    rom_down_deg: float = 30.0
    # Resting tremor RMS (degrees of relative tilt jitter at rest)
    tremor_rms_deg: float = 0.5
    # PCA functional axis rotation (radians)
    axis_theta_rad: float = 0.0
    # Hysteresis & timing
    t_on: float = 0.15
    t_off: float = 0.09
    hold_time: float = 0.6
    reaction_time: float = 0.3
    cooldown: float = 0.5
    # Accessible / spasm gate options
    spasm_gate_enabled: bool = False
    spasm_min_burst_s: float = 0.15
    spasm_jerk_threshold: float = 40.0
    calibrated_profile: bool = False

    # ── Derived settings (§7.6) ───────────────────────────────────────────
    def derive_thresholds(self) -> None:
        """Recompute t_on, t_off and cooldown from tremor_rms_deg, ROM and reaction_time."""
        rom_min = max(5.0, min(self.rom_left_deg, self.rom_right_deg,
                               self.rom_up_deg, self.rom_down_deg))
        raw_t_on = 3.0 * self.tremor_rms_deg / rom_min
        self.t_on = round(max(0.15, min(0.65, raw_t_on)), 4)
        self.t_off = round(0.6 * self.t_on, 4)
        self.cooldown = round(max(0.5, 1.5 * self.reaction_time), 4)

    # ── Step 1: Rest (neutral pose + tremor amplitude) ────────────────────
    def calibrate_rest(self, frames: Sequence[Frame],
                       quats: Optional[Sequence[Quat]] = None) -> None:
        if quats:
            self.q_base = q_average(quats)
        elif frames:
            self.q_base = q_average((f.qw, f.qx, f.qy, f.qz) for f in frames)
        if not frames:
            return
        med_r = _median([f.roll for f in frames])
        med_p = _median([f.pitch for f in frames])
        sq = [(f.roll - med_r) ** 2 + (f.pitch - med_p) ** 2 for f in frames]
        self.tremor_rms_deg = round(math.sqrt(sum(sq) / len(sq)), 4)
        self.derive_thresholds()

    # ── Step 2: Reach (90th-percentile per-side ROM) ──────────────────────
    def calibrate_reach(self, frames: Sequence[Frame], min_rom_deg: float = 5.0) -> None:
        """Compute per-side ROM from comfortable reaches using 90th percentile.

        Frame sign conventions (matches Frontend):
          tilt_gx > 0 → right,  tilt_gx < 0 → left
          tilt_gy > 0 → down,   tilt_gy < 0 → up
        Angle in degrees along each axis is asin(clamp(tilt_g, -1, 1)).
        """
        rights, lefts, downs, ups = [], [], [], []
        for f in frames:
            ax_deg = math.degrees(math.asin(max(-1.0, min(1.0, f.tilt_gx))))
            ay_deg = math.degrees(math.asin(max(-1.0, min(1.0, f.tilt_gy))))
            if ax_deg > 0:
                rights.append(ax_deg)
            elif ax_deg < 0:
                lefts.append(-ax_deg)
            if ay_deg > 0:
                downs.append(ay_deg)
            elif ay_deg < 0:
                ups.append(-ay_deg)
        if lefts:
            self.rom_left_deg = round(max(min_rom_deg, _percentile(lefts, 90.0)), 2)
        if rights:
            self.rom_right_deg = round(max(min_rom_deg, _percentile(rights, 90.0)), 2)
        if ups:
            self.rom_up_deg = round(max(min_rom_deg, _percentile(ups, 90.0)), 2)
        if downs:
            self.rom_down_deg = round(max(min_rom_deg, _percentile(downs, 90.0)), 2)
        self.derive_thresholds()

    # ── Step 3: Natural swing (PCA movement axis θ) ───────────────────────
    def calibrate_swing(self, frames: Sequence[Frame]) -> None:
        pts = [(f.tilt_gx, f.tilt_gy) for f in frames]
        self.calibrate_swing_xy(pts)

    def calibrate_swing_xy(self, tilt_samples: Sequence[Tuple[float, float]]) -> None:
        n = len(tilt_samples)
        if n < 10:
            return
        mx = sum(p[0] for p in tilt_samples) / n
        my = sum(p[1] for p in tilt_samples) / n
        cxx = sum((p[0] - mx) ** 2 for p in tilt_samples)
        cxy = sum((p[0] - mx) * (p[1] - my) for p in tilt_samples)
        cyy = sum((p[1] - my) ** 2 for p in tilt_samples)
        if cxx == cyy and cxy == 0:
            return
        self.axis_theta_rad = round(0.5 * math.atan2(2.0 * cxy, cxx - cyy), 5)

    # ── Step 4: Hold duration ─────────────────────────────────────────────
    def calibrate_hold(self, hold_durations_s: Sequence[float]) -> None:
        valid = [d for d in hold_durations_s if d > 0]
        if not valid:
            return
        self.hold_time = round(max(0.25, min(2.5, 0.6 * _median(valid))), 3)

    # ── Step 5: Reaction latency ──────────────────────────────────────────
    def calibrate_reaction(self, latencies_s: Sequence[float]) -> None:
        valid = [d for d in latencies_s if d > 0]
        if not valid:
            return
        self.reaction_time = round(max(0.1, min(3.0, _median(valid))), 3)
        self.derive_thresholds()

    # ── Persistence (data/profiles/{username}.json) ───────────────────────
    def save(self, directory: Path = PROFILES_DIR) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{self.username}.json"
        existing = {}
        if path.exists():
            try:
                existing = json.loads(path.read_text())
            except Exception:
                existing = {}
        payload = asdict(self)
        payload["q_base"] = list(q_normalize(self.q_base))
        existing.update(payload)
        path.write_text(json.dumps(existing, indent=2))
        return path

    @classmethod
    def load(cls, username: str, directory: Path = PROFILES_DIR) -> "ChildProfile":
        path = directory / f"{username}.json"
        if not path.exists():
            return cls(username=username)
        try:
            raw = json.loads(path.read_text())
        except Exception:
            return cls(username=username)
        known = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in raw.items() if k in known}
        if "q_base" in filtered and isinstance(filtered["q_base"], (list, tuple)) and len(filtered["q_base"]) == 4:
            filtered["q_base"] = q_normalize(tuple(filtered["q_base"]))
        else:
            filtered.pop("q_base", None)
        if filtered.get("mount_location") not in VALID_MOUNTS:
            filtered["mount_location"] = "dorsal_hand"
        return cls(**filtered)

