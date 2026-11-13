"""
frontend.py — Signal frontend: IMUSample → Frame  (roadmap §6, §7.1, §7.2)

Responsibilities
────────────────
1. Orientation source: hardware Bosch quaternion when `hw_fusion_valid`,
   otherwise the software Madgwick filter (raw acc/gyro fallback).
2. Neutral pose:  q_base captured at rest; q_rel = q_base⁻¹ ⊗ q.
3. Tilt: gravity direction derived from the quaternion (no motion
   acceleration, no EMA lag), expressed in the neutral frame (yaw-immune),
   filtered with a 2nd-order 3 Hz Butterworth.  Units are g, identical in
   sign/scale to the legacy `smooth_ax - cal_ax` tilt so existing
   thresholds keep working.
4. ROM-normalised tilt (-1..1) for detectors/pointer.
5. Linear acceleration (gravity removed), 10 Hz Butterworth.
6. Sample-rate estimate: filters are re-designed when the measured rate
   differs from the design rate by > 15 %.

Pure Python, no threads, no pygame — fully replayable.
"""

from __future__ import annotations

import logging
import math
from collections import deque
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

from shared.fusion_processor import FusionProcessor
from shared.gestures.types import Frame, Signals
from shared.quat import (
    IDENTITY, Quat, Vec3, euler_from_q, gravity_from_q, q_average, q_conj,
    q_from_two_vectors, q_relative, q_rotate, v_normalize,
)

logger = logging.getLogger(__name__)


# ── Butterworth biquad ────────────────────────────────────────────────────────

def butter2_lowpass(fc: float, fs: float) -> Tuple[Tuple[float, float, float], Tuple[float, float, float]]:
    """2nd-order Butterworth low-pass via bilinear transform.

    Returns (b, a) with a[0] == 1, identical to scipy.signal.butter(2, fc, fs=fs).
    """
    fc = min(fc, 0.45 * fs)  # keep below Nyquist
    k = math.tan(math.pi * fc / fs)
    k2 = k * k
    sq2 = math.sqrt(2.0)
    norm = 1.0 / (1.0 + sq2 * k + k2)
    b0 = k2 * norm
    return (b0, 2.0 * b0, b0), (1.0, 2.0 * (k2 - 1.0) * norm, (1.0 - sq2 * k + k2) * norm)


class Biquad:
    """Direct-form-I biquad:  y = b0x + b1x₁ + b2x₂ − a1y₁ − a2y₂."""

    __slots__ = ("b", "a", "x1", "x2", "y1", "y2", "_primed")

    def __init__(self, b, a):
        self.b, self.a = tuple(b), tuple(a)
        self.x1 = self.x2 = self.y1 = self.y2 = 0.0
        self._primed = False

    def set_coeffs(self, b, a) -> None:
        self.b, self.a = tuple(b), tuple(a)

    def reset(self, value: float = 0.0) -> None:
        """Initialise to steady state at `value` (no start-up transient)."""
        self.x1 = self.x2 = self.y1 = self.y2 = value
        self._primed = True

    def __call__(self, x: float) -> float:
        if not self._primed:
            self.reset(x)
        b0, b1, b2 = self.b
        _, a1, a2 = self.a
        y = b0 * x + b1 * self.x1 + b2 * self.x2 - a1 * self.y1 - a2 * self.y2
        self.x2, self.x1 = self.x1, x
        self.y2, self.y1 = self.y1, y
        return y


# ── Sample-rate estimator ─────────────────────────────────────────────────────

class RateEstimator:
    """Robust sample-rate estimate from arrival timestamps (BLE bursts tolerated)."""

    def __init__(self, nominal_fs: float = 100.0, window: int = 200):
        self.nominal_fs = nominal_fs
        self._ts: deque = deque(maxlen=window)
        self._dts: deque = deque(maxlen=window)

    def update(self, t: float) -> None:
        if self._ts:
            self._dts.append(t - self._ts[-1])
        self._ts.append(t)

    @property
    def fs(self) -> float:
        if len(self._ts) < 20:
            return self.nominal_fs
        span = self._ts[-1] - self._ts[0]
        if span <= 0:
            return self.nominal_fs
        return (len(self._ts) - 1) / span

    @property
    def dt(self) -> float:
        return 1.0 / max(self.fs, 1e-3)

    @property
    def jitter(self) -> float:
        """Std-dev of arrival intervals (s)."""
        n = len(self._dts)
        if n < 2:
            return 0.0
        m = sum(self._dts) / n
        return math.sqrt(sum((d - m) ** 2 for d in self._dts) / (n - 1))


# ── Frontend ──────────────────────────────────────────────────────────────────

@dataclass
class FrontendConfig:
    nominal_fs: float = 100.0
    control_cutoff_hz: float = 3.0      # tilt / pointer (keeps <2 Hz voluntary, cuts tremor)
    feature_cutoff_hz: float = 10.0     # linear acceleration / features
    calibration_seconds: float = 1.0
    calibration_samples: int = 100      # fallback cap when timestamps are synthetic/tight
    # Per-side range of motion (degrees) used to normalise tilt to -1..1
    rom_left_deg: float = 30.0
    rom_right_deg: float = 30.0
    rom_up_deg: float = 30.0
    rom_down_deg: float = 30.0
    # PCA functional axis rotation (radians)
    axis_theta_rad: float = 0.0
    # Adaptive baseline (washout) — re-centers smoothly when resting after a gesture
    adapt_tau_s: float = 3.0            # normal washout time constant
    adapt_still_tau_s: float = 1.2      # faster re-baseline after resting > 0.6 s
    adapt_gyro_threshold: float = 45.0  # °/s — adapt only below this
    madgwick_beta: float = 0.033


class Frontend:
    """Turns IMUSamples into Frames.  Not thread-safe: call from one thread."""

    def __init__(self, config: Optional[FrontendConfig] = None):
        self.cfg = config or FrontendConfig()
        self.rate = RateEstimator(self.cfg.nominal_fs)
        self._design_fs = self.cfg.nominal_fs
        self._fusion = FusionProcessor(self.cfg.madgwick_beta)
        self._last_t: float = 0.0

        b, a = butter2_lowpass(self.cfg.control_cutoff_hz, self._design_fs)
        self._ctl = [Biquad(b, a) for _ in range(3)]          # gravity x/y/z
        b, a = butter2_lowpass(self.cfg.feature_cutoff_hz, self._design_fs)
        self._feat = [Biquad(b, a) for _ in range(3)]         # lin acc x/y/z

        # Calibration state
        self.calibrated: bool = False
        self._cal_q: list = []
        self._cal_g: list = []
        self._cal_t0: Optional[float] = None
        self.q_base: Quat = IDENTITY
        self.g_base: Vec3 = (0.0, 0.0, 1.0)
        self._q_align: Quat = IDENTITY

        # Hardware quaternion convention auto-check (first ~50 still samples)
        self._conv_n = 0
        self._conv_err = [0.0, 0.0]
        self._conv_conj: Optional[bool] = None

        self.adapt_paused: bool = False
        self._still_since: Optional[float] = None

        # Outputs useful to legacy consumers
        self.q_abs: Quat = IDENTITY
        self.euler_abs: Vec3 = (0.0, 0.0, 0.0)
        self.raw_tilt_g: Tuple[float, float] = (0.0, 0.0)   # before PCA rotation
        self.last_frame: Optional[Frame] = None

    # ── configuration ─────────────────────────────────────────────────────
    def set_rom(self, left: float, right: float, up: float, down: float) -> None:
        self.cfg.rom_left_deg, self.cfg.rom_right_deg = left, right
        self.cfg.rom_up_deg, self.cfg.rom_down_deg = up, down

    def recalibrate(self) -> None:
        self.calibrated = False
        self._cal_q.clear()
        self._cal_g.clear()
        self._cal_t0 = None

    def set_baseline(self, q_base: Sequence[float]) -> None:
        """Set neutral pose directly (e.g. from a saved profile)."""
        self.q_base = tuple(q_base)  # type: ignore[assignment]
        self._set_g_base(gravity_from_q(self.q_base))
        self.calibrated = True

    def _set_g_base(self, g: Sequence[float]) -> None:
        self.g_base = v_normalize(g)
        self._q_align = q_from_two_vectors(self.g_base, (0.0, 0.0, 1.0))

    # ── main entry ────────────────────────────────────────────────────────
    def process(self, s) -> Frame:
        t = s.timestamp
        raw_dt = (t - self._last_t) if self._last_t > 0 else 1.0 / self.cfg.nominal_fs
        self._last_t = t
        self.rate.update(t)
        self._maybe_redesign()
        dt = self.rate.dt

        # 1. orientation
        if getattr(s, "hw_fusion_valid", False) and _has_hw_quat(s):
            q = (s.hw_qw, s.hw_qx, s.hw_qy, s.hw_qz)
            q = self._check_convention(q, (s.ax, s.ay, s.az))
        else:
            st = self._fusion.process(s, raw_dt)
            q = (st.qw, st.qx, st.qy, st.qz)
        self.q_abs = q
        self.euler_abs = euler_from_q(q)

        g = gravity_from_q(q)
        av = math.sqrt(s.gx * s.gx + s.gy * s.gy + s.gz * s.gz)

        # 2. linear acceleration (gravity removed) — 10 Hz
        lin = (self._feat[0](s.ax - g[0]), self._feat[1](s.ay - g[1]), self._feat[2](s.az - g[2]))

        # 3. control-filtered gravity — 3 Hz
        gf = (self._ctl[0](g[0]), self._ctl[1](g[1]), self._ctl[2](g[2]))

        # 4. calibration (time-based in seconds, or sample-count cap)
        if not self.calibrated:
            if self._cal_t0 is None:
                self._cal_t0 = t
            self._cal_q.append(q)
            self._cal_g.append(gf)
            elapsed = t - self._cal_t0
            if ((elapsed >= self.cfg.calibration_seconds - 1e-6 and len(self._cal_q) >= 5)
                    or len(self._cal_q) >= self.cfg.calibration_samples):
                self._finish_calibration()
                # Recompute neutral-frame alignment immediately so this sample is usable
        elif not self.adapt_paused and av < self.cfg.adapt_gyro_threshold:
            if av < 12.0:
                if self._still_since is None:
                    self._still_since = t
                tau = self.cfg.adapt_still_tau_s if (t - self._still_since) >= 0.6 else self.cfg.adapt_tau_s
            else:
                self._still_since = None
                tau = self.cfg.adapt_tau_s
            k = 1.0 - math.exp(-dt / max(tau, 1e-3))
            gb = self.g_base
            self._set_g_base((gb[0] + k * (gf[0] - gb[0]),
                              gb[1] + k * (gf[1] - gb[1]),
                              gb[2] + k * (gf[2] - gb[2])))
        else:
            self._still_since = None

        # 5. tilt in neutral frame
        ga = q_rotate(self._q_align, gf)
        raw_tx, raw_ty = ga[0], ga[1]
        self.raw_tilt_g = (raw_tx, raw_ty)
        c, sn = math.cos(self.cfg.axis_theta_rad), math.sin(self.cfg.axis_theta_rad)
        tx = raw_tx * c + raw_ty * sn
        ty = -raw_tx * sn + raw_ty * c
        roll = math.degrees(math.atan2(ga[1], ga[2]))
        pitch = math.degrees(math.atan2(-ga[0], math.sqrt(ga[1] ** 2 + ga[2] ** 2)))

        rom_x = self.cfg.rom_right_deg if tx >= 0 else self.cfg.rom_left_deg
        rom_y = self.cfg.rom_down_deg if ty >= 0 else self.cfg.rom_up_deg
        tilt_x = _clamp(tx / max(math.sin(math.radians(rom_x)), 1e-3))
        tilt_y = _clamp(ty / max(math.sin(math.radians(rom_y)), 1e-3))

        q_rel = q_relative(self.q_base, q)
        yaw = euler_from_q(q_rel)[2]

        frame = Frame(
            t=t, dt=dt,
            qw=q_rel[0], qx=q_rel[1], qy=q_rel[2], qz=q_rel[3],
            roll=roll, pitch=pitch, yaw=yaw,
            gx=s.gx, gy=s.gy, gz=s.gz,
            lin_ax=lin[0], lin_ay=lin[1], lin_az=lin[2],
            tilt_gx=tx if self.calibrated else 0.0,
            tilt_gy=ty if self.calibrated else 0.0,
            tilt_x=tilt_x if self.calibrated else 0.0,
            tilt_y=tilt_y if self.calibrated else 0.0,
            av_magnitude=av,
            calibrated=self.calibrated,
        )
        self.last_frame = frame
        return frame

    def signals(self, hold_progress: float = 0.0, hold_direction: str = "") -> Signals:
        f = self.last_frame
        if f is None:
            return Signals()
        return Signals(
            tilt_x=f.tilt_x, tilt_y=f.tilt_y,
            pointer_x=0.5 * (1.0 + f.tilt_x), pointer_y=0.5 * (1.0 + f.tilt_y),
            roll=f.roll, pitch=f.pitch,
            gx=f.gx, gy=f.gy, gz=f.gz,
            hold_progress=hold_progress, hold_direction=hold_direction,
            calibrated=f.calibrated,
        )

    # ── internals ─────────────────────────────────────────────────────────
    def _finish_calibration(self) -> None:
        n = len(self._cal_g)
        med = [sorted(v[i] for v in self._cal_g)[n // 2] for i in range(3)]
        self._set_g_base(med)
        self.q_base = q_average(self._cal_q)
        self.calibrated = True
        self._cal_q.clear()
        self._cal_g.clear()
        logger.info("Frontend calibrated — neutral gravity (%.3f, %.3f, %.3f)", *self.g_base)

    def _maybe_redesign(self) -> None:
        fs = self.rate.fs
        if len(self.rate._ts) < 50:
            return
        if abs(fs - self._design_fs) / self._design_fs > 0.15:
            logger.info("Frontend: measured %.1f Hz (designed for %.1f) — redesigning filters",
                        fs, self._design_fs)
            self._design_fs = fs
            b, a = butter2_lowpass(self.cfg.control_cutoff_hz, fs)
            for f in self._ctl:
                f.set_coeffs(b, a)
            b, a = butter2_lowpass(self.cfg.feature_cutoff_hz, fs)
            for f in self._feat:
                f.set_coeffs(b, a)

    def _check_convention(self, q: Quat, acc: Vec3) -> Quat:
        """Detect whether the hardware quaternion uses the inverse convention."""
        if self._conv_conj is None:
            na = math.sqrt(acc[0] ** 2 + acc[1] ** 2 + acc[2] ** 2)
            if abs(na - 1.0) < 0.1:
                an = (acc[0] / na, acc[1] / na, acc[2] / na)
                for i, cand in enumerate((q, q_conj(q))):
                    g = gravity_from_q(cand)
                    self._conv_err[i] += sum((g[k] - an[k]) ** 2 for k in range(3))
                self._conv_n += 1
                if self._conv_n >= 50:
                    self._conv_conj = self._conv_err[1] < 0.5 * self._conv_err[0]
                    if self._conv_conj:
                        logger.warning("Hardware quaternion uses inverse convention — conjugating")
        return q_conj(q) if self._conv_conj else q


def _has_hw_quat(s) -> bool:
    return hasattr(s, "hw_qw") and (s.hw_qw or s.hw_qx or s.hw_qy or s.hw_qz)


def _clamp(v: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return lo if v < lo else hi if v > hi else v

