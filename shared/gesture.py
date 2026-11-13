"""
gesture.py — Wrist-gesture engine (Frontend + Detector plug-ins + Event queue)

Converts IMU samples from the MetaMotion sensor into:
  • discrete GestureEvents drained via `poll()` (never missed between frames)
  • continuous Signals read via `signals()` (ROM-normalised tilt, pointer, hold ring)
  • legacy `GestureState` snapshot via `get_state()` (full backward compatibility)

Architecture (see docs/v1.0-raodmap.md §6–§7):
  IMUSample → Frontend (q_rel = q_base⁻¹ ⊗ q, 3 Hz / 10 Hz Butterworth biquads)
            → Frame    → Ring buffer
                       → Detectors (Flick, Steer, Twist, Slice, Hold, Dwell, AnyMove, Still)
                       → SpasmGate (optional jerk + duration filter)
                       → Event queue + Signals + legacy GestureState shim
"""

import logging
import math
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass, replace
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

from shared.child_profile import ChildProfile
from shared.frontend import Frontend, FrontendConfig
from shared.fusion_processor import FusionProcessor
from shared.gesture_detector import SliceDetector
from shared.gestures.accessible import (
    AnyMoveDetector, DwellDetector, HoldDetector, SpasmGate, StillDetector,
)
from shared.gestures.detectors import (
    FLICK_UP_GY_SIGN, FlickDetector, SliceAdapter, SteerDetector, TwistDetector,
)
from shared.gestures.types import Detector, Frame, Gesture, GestureEvent, Signals
from shared.sensor import IMUSample


# ── Configuration ─────────────────────────────────────────────────────────────

@dataclass
class GestureConfig:
    # Tilt dead-zone in g (calibration-relative lateral gravity shift).
    # ~0.05 g ≈ 3° of tilt — keeps paddle still when wrist is approximately flat.
    tilt_threshold: float = 0.05

    # Tilt value (g) at which paddle reaches full speed.
    # 0.5 g ≈ 30° of tilt — comfortable range for fast play.
    tilt_max: float = 0.5

    # Gyroscope flick threshold (°/s) to trigger a LAUNCH event.
    # 200°/s catches a firm-but-normal wrist flick; 300 was too high in practice.
    flick_threshold: float = 200.0

    # Legacy EMA smoothing factor [0–1] kept for abs_ax/ay/az display & raw_gz.
    # Note: α = 0.05 gives τ = Δt(1−α)/α = 0.19 s → fc ≈ 0.84 Hz at 100 Hz
    # (0.42 Hz at 50 Hz), NOT 2 Hz.  Control tilt now uses Frontend's 3 Hz
    # 2nd-order Butterworth filter on quaternion gravity (roadmap §4.1 & §7.1–7.2).
    alpha: float = 0.05

    # Rolling window for flick detection.
    # Defined in seconds (`flick_window_s`); `flick_window` kept for compatibility.
    flick_window: int = 6
    flick_window_s: float = 0.06

    # Dead-zone for gyro twist (°/s).
    twist_dead_zone: float = 30.0

    # Time (s) between repeated LAUNCH events to prevent accidental double-fire.
    launch_cooldown: float = 0.4

    # Auto-calibration duration (seconds) and fallback sample count.
    calibration_samples: int = 100
    calibration_seconds: float = 1.0

    # Minimum seconds between gesture triggers on each axis (used by games).
    gesture_cooldown: float = 0.8

    # Functional alignment angle (radians) from PCA swing calibration.
    yaw_offset_rads: float = 0.0

    # Gyroscope magnitude (°/s) below which the adaptive baseline is allowed to
    # drift toward the current resting gravity vector.
    gyro_adapt_threshold: float = 45.0

    # Rate at which the adaptive baseline drifts toward rest (0.002 @ 100 Hz → τ ≈ 5 s).
    adapt_rate: float = 0.002

    # Duration (seconds) of the functional-calibration data-collection window.
    functional_cal_seconds: float = 2.5

    # Flick-to-steer mode (for Snake)
    flick_steer_enabled: bool = False
    flick_steer_threshold: float = 160.0  # °/s, lower than launch flick
    flick_steer_cooldown: float = 0.5     # seconds between directional flicks
    flick_steer_window: int = 7           # legacy sample count
    flick_steer_window_s: float = 0.07    # window in seconds

    # Accessible hold / dwell / spasm-gate parameters (roadmap §7.3–7.5)
    hold_t_on: float = 0.25               # Schmitt-trigger turn-on (ROM-normalised 0..1)
    hold_t_off: float = 0.15              # Schmitt-trigger turn-off
    hold_time: float = 0.6                # seconds to hold before firing HOLD_*
    dwell_time: float = 1.0               # seconds pointer stays in target for DWELL
    any_move_threshold: float = 40.0      # °/s for single-switch ANY_MOVE
    any_move_duration: float = 0.2        # seconds above threshold
    spasm_gate_enabled: bool = False      # enable rule-based SpasmGate (§7.5)
    spasm_min_burst_s: float = 0.15
    spasm_jerk_threshold: float = 40.0    # g/s
    haptics_enabled: bool = False         # disabled per-gesture; celebrations & >30s rest handle haptics


# Pre-defined configs for different game modes.
CONFIG_STANDARD = GestureConfig()

# ASTRA / Accessible mode: lower thresholds, longer cooldowns, and disabled spin
# make the game more forgiving for users with movement disabilities.
CONFIG_ACCESSIBLE = GestureConfig(
    tilt_threshold=0.04,      # More sensitive to small tilts
    tilt_max=0.4,             # Reach full speed with less effort
    flick_threshold=120.0,    # Lower flick threshold for launching
    twist_dead_zone=999.0,    # Effectively disables ball spin control
    launch_cooldown=1.0,      # Longer cooldown to prevent accidental double-launches
    gesture_cooldown=1.2,
)

# Variant of accessible mode for Snake that uses discrete flicks to turn.
CONFIG_ACCESSIBLE_FLICK_STEER = replace(
    CONFIG_ACCESSIBLE,
    flick_steer_enabled=True,
)


# ── Gesture state (legacy snapshot) ───────────────────────────────────────────

@dataclass
class GestureState:
    """Published to the game on every update tick (backward-compatible snapshot)."""
    paddle_velocity: float = 0.0
    launch: bool = False
    spin: float = 0.0
    tilt_y: float = 0.0
    raw_ax: float = 0.0
    raw_gz: float = 0.0
    calibrated: bool = False
    # Absolute IMU values for calibration visualizer
    abs_ax: float = 0.0
    abs_ay: float = 0.0
    abs_az: float = 0.0
    abs_gx: float = 0.0
    abs_gy: float = 0.0
    abs_gz: float = 0.0
    # Sensor fusion (hardware quaternion when available, software Madgwick fallback)
    qw: float = 1.0
    qx: float = 0.0
    qy: float = 0.0
    qz: float = 0.0
    euler_roll: float = 0.0
    euler_pitch: float = 0.0
    euler_yaw: float = 0.0
    av_magnitude: float = 0.0
    # Linear acceleration (g, gravity removed)
    lin_ax: float = 0.0
    lin_ay: float = 0.0
    lin_az: float = 0.0
    # Orientation relative to neutral baseline q_base (degrees)
    rel_roll: float = 0.0
    rel_pitch: float = 0.0
    rel_yaw: float = 0.0
    # Hold progress (0..1) while HoldDetector is ARMING
    hold_progress: float = 0.0
    hold_direction: str = ""
    # Slice detection
    slice_active: bool = False
    slice_direction: str = ""
    combo_count: int = 0
    # Flick-to-steer outputs
    steer_left: bool = False
    steer_right: bool = False
    steer_up: bool = False
    steer_down: bool = False
    # Functional calibration
    functional_calibrating: bool = False
    # BMM150 magnetometer calibration state (0 = offline … 3 = fully calibrated)
    mag_cal_state: int = 0
    # Bosch hardware fusion outputs
    hw_heading: float = 0.0
    hw_fusion_valid: bool = False
    # True after ~3 s of no samples — games can show a "sensor disconnected" overlay
    sensor_disconnected: bool = False


# ── Main interpreter ──────────────────────────────────────────────────────────

class GestureInterpreter:
    """
    Drains the sensor queue, runs Frontend + Detector plug-ins + SpasmGate,
    and publishes:
      • `poll()`      → list[GestureEvent] queued since last call
      • `signals()`   → continuous Signals (tilt_x/y, pointer_x/y, hold_progress)
      • `get_state()` → legacy GestureState snapshot
    """

    def __init__(
        self,
        sensor_queue: queue.Queue,
        config: Optional[GestureConfig] = None,
        sensor=None,
        profile: Optional[ChildProfile] = None,
    ):
        self._q = sensor_queue
        self.config = config or GestureConfig()
        self.state = GestureState()
        self.sensor = sensor
        self._sensor = sensor
        self._lock = threading.Lock()

        # Frontend (quaternion baseline + Butterworth biquads)
        fe_cfg = FrontendConfig(
            calibration_seconds=self.config.calibration_seconds,
            calibration_samples=self.config.calibration_samples,
            axis_theta_rad=self.config.yaw_offset_rads,
            adapt_gyro_threshold=self.config.gyro_adapt_threshold,
            rom_left_deg=self._tilt_max_to_rom_deg(self.config.tilt_max),
            rom_right_deg=self._tilt_max_to_rom_deg(self.config.tilt_max),
            rom_up_deg=self._tilt_max_to_rom_deg(self.config.tilt_max),
            rom_down_deg=self._tilt_max_to_rom_deg(self.config.tilt_max),
        )
        self.frontend = Frontend(fe_cfg)
        self.buffer: deque = deque(maxlen=500)  # ~5–10 s of Frames

        # Built-in detector plug-ins
        self._flick_det = FlickDetector(
            threshold=self.config.flick_threshold,
            window_s=self.config.flick_window_s,
            cooldown=self.config.launch_cooldown,
        )
        self._steer_det = SteerDetector(
            threshold=self.config.flick_steer_threshold,
            window_s=self.config.flick_steer_window_s,
            cooldown=self.config.flick_steer_cooldown,
        )
        self._twist_det = TwistDetector(dead_zone=self.config.twist_dead_zone)
        self._slice_det = SliceAdapter()
        self._hold_x = HoldDetector("x", t_on=self.config.hold_t_on,
                                    t_off=self.config.hold_t_off,
                                    hold_time=self.config.hold_time)
        self._hold_y = HoldDetector("y", t_on=self.config.hold_t_on,
                                    t_off=self.config.hold_t_off,
                                    hold_time=self.config.hold_time)
        self._dwell_det = DwellDetector(dwell_time=self.config.dwell_time)
        self._any_move_det = AnyMoveDetector(
            threshold=self.config.any_move_threshold,
            min_duration=self.config.any_move_duration,
            cooldown=self.config.gesture_cooldown,
        )
        self._still_det = StillDetector()
        self._extra_detectors: List[Detector] = []

        self.gate = SpasmGate(
            min_burst_s=self.config.spasm_min_burst_s,
            jerk_threshold=self.config.spasm_jerk_threshold,
        )

        # Queued events & continuous signals
        self._events: deque = deque(maxlen=256)
        self._signals: Signals = Signals()

        # Legacy EMA state for abs_ax/ay/az visualizer & raw_gz
        self._smooth_ax: float = 0.0
        self._smooth_ay: float = 0.0
        self._smooth_az: float = 0.0
        self._smooth_gz: float = 0.0
        self._calibrated: bool = False

        # Functional calibration (PCA swing)
        self._functional_calibrating: bool = False
        self._functional_cal_buf: List[Tuple[float, float]] = []
        self._functional_cal_t0: Optional[float] = None

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._sample_count: int = 0
        self._last_sample_time: float = 0.0
        self._disconnect_reported: bool = False
        self._last_haptic_time: float = -1e9

        # Legacy attribute aliases
        self._slice: SliceDetector = self._slice_det.detector

        if profile is not None:
            self.apply_profile(profile)

    @staticmethod
    def _tilt_max_to_rom_deg(tilt_max: float) -> float:
        return math.degrees(math.asin(max(0.08, min(1.0, tilt_max))))

    # ── Plug-in & profile API ─────────────────────────────────────────────

    @property
    def detectors(self) -> List[Detector]:
        base: List[Detector] = [
            self._flick_det,
            self._twist_det,
            self._slice_det,
            self._hold_x,
            self._hold_y,
            self._dwell_det,
            self._any_move_det,
            self._still_det,
        ]
        if self.config.flick_steer_enabled:
            base.insert(1, self._steer_det)
        return base + self._extra_detectors

    def register_detector(self, detector: Detector) -> None:
        """Register an additional Detector plug-in without modifying `_process`."""
        with self._lock:
            self._extra_detectors.append(detector)

    def apply_profile(self, profile: ChildProfile) -> None:
        """Apply a per-child calibration profile (§7.6) to Frontend, Config and Detectors."""
        with self._lock:
            self.frontend.set_rom(
                profile.rom_left_deg, profile.rom_right_deg,
                profile.rom_up_deg, profile.rom_down_deg,
            )
            self.frontend.cfg.axis_theta_rad = profile.axis_theta_rad
            if profile.calibrated_profile and any(profile.q_base):
                self.frontend.set_baseline(profile.q_base)
            self.config.yaw_offset_rads = profile.axis_theta_rad
            self.config.hold_t_on = profile.t_on
            self.config.hold_t_off = profile.t_off
            self.config.hold_time = profile.hold_time
            self.config.gesture_cooldown = profile.cooldown
            self.config.launch_cooldown = max(self.config.launch_cooldown, profile.cooldown)
            self.config.spasm_gate_enabled = profile.spasm_gate_enabled
            self.config.spasm_min_burst_s = profile.spasm_min_burst_s
            self.config.spasm_jerk_threshold = profile.spasm_jerk_threshold
            # Convert ROM + t_on back into g-units for legacy paddle dead-zone
            rom_min_rad = math.radians(max(5.0, min(profile.rom_left_deg, profile.rom_right_deg)))
            self.config.tilt_max = round(math.sin(rom_min_rad), 4)
            self.config.tilt_threshold = round(profile.t_on * self.config.tilt_max, 4)
            self._sync_config()

    def _sync_config(self) -> None:
        """Propagate dynamic `self.config` changes to Frontend and Detectors."""
        cfg = self.config
        self.frontend.cfg.axis_theta_rad = cfg.yaw_offset_rads
        self.frontend.cfg.adapt_gyro_threshold = cfg.gyro_adapt_threshold
        self.frontend.cfg.calibration_seconds = cfg.calibration_seconds
        self.frontend.cfg.calibration_samples = cfg.calibration_samples

        self._flick_det.threshold = cfg.flick_threshold
        self._flick_det.window_s = max(cfg.flick_window_s, cfg.flick_window * 0.01)
        self._flick_det.cooldown = cfg.launch_cooldown

        self._steer_det.threshold = cfg.flick_steer_threshold
        self._steer_det.window_s = max(cfg.flick_steer_window_s, cfg.flick_steer_window * 0.01)
        self._steer_det.cooldown = cfg.flick_steer_cooldown

        self._twist_det.dead_zone = cfg.twist_dead_zone

        for h in (self._hold_x, self._hold_y):
            h.t_on = cfg.hold_t_on
            h.t_off = cfg.hold_t_off
            h.hold_time = cfg.hold_time

        self._dwell_det.dwell_time = cfg.dwell_time
        self._any_move_det.threshold = cfg.any_move_threshold
        self._any_move_det.min_duration = cfg.any_move_duration
        self._any_move_det.cooldown = cfg.gesture_cooldown

        self.gate.min_burst_s = cfg.spasm_min_burst_s
        self.gate.jerk_threshold = cfg.spasm_jerk_threshold

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="gesture-interp"
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)

    def vibrate(self, duration: float = 0.15) -> None:
        """Trigger haptic buzz on the sensor (no-op if no sensor attached)."""
        if self._sensor is not None:
            self._sensor.vibrate(duration)

    def save_calibration_to_nvm(self) -> None:
        """Persist current magnetometer calibration offsets to sensor NVM."""
        if self._sensor is not None:
            self._sensor.save_calibration_to_nvm()

    def recalibrate(self) -> None:
        """Force a new calibration cycle (call when sensor position changes)."""
        with self._lock:
            self.frontend.recalibrate()
            self._calibrated = False
            self.state.calibrated = False
            for d in self.detectors:
                d.reset()
            self.gate.reset()
        logger.info("Recalibration started — hold sensor still…")

    def start_functional_calibration(self) -> None:
        """Triggers a functional_cal_seconds window to learn the natural swing axis."""
        with self._lock:
            self._functional_calibrating = True
            self._functional_cal_buf.clear()
            self._functional_cal_t0 = None
        logger.info("Functional calibration started — swing left and right…")

    def align_functional_axis(self, tilt_samples: List[Tuple[float, float]]) -> None:
        """
        Medical-Grade Functional Calibration (PCA).
        Takes a list of raw (tilt_x, tilt_y) points from a natural arm motion,
        finds the primary axis of motion, and rotates the coordinates to match it.
        """
        n = len(tilt_samples)
        if n < 10:
            return

        mean_x = sum(v[0] for v in tilt_samples) / n
        mean_y = sum(v[1] for v in tilt_samples) / n

        cxx = sum((v[0] - mean_x) ** 2 for v in tilt_samples)
        cxy = sum((v[0] - mean_x) * (v[1] - mean_y) for v in tilt_samples)
        cyy = sum((v[1] - mean_y) ** 2 for v in tilt_samples)

        if cxx == cyy and cxy == 0:
            return

        angle = 0.5 * math.atan2(2 * cxy, cxx - cyy)
        with self._lock:
            self.config.yaw_offset_rads = angle
            self.frontend.cfg.axis_theta_rad = angle
        logger.info("PCA Functional Calibration: Rotated axes by %.1f°", math.degrees(angle))

    # ── Public consumer API (§6.3) ────────────────────────────────────────

    def poll(self) -> List[GestureEvent]:
        """Drain and return all GestureEvents accumulated since the last call."""
        with self._lock:
            events = list(self._events)
            self._events.clear()
            return events

    def signals(self) -> Signals:
        """Return latest continuous control signals."""
        with self._lock:
            return self._signals

    def get_state(self) -> GestureState:
        """Thread-safe snapshot of the latest legacy GestureState."""
        with self._lock:
            return replace(self.state)

    # ── Processing loop ────────────────────────────────────────────────────────

    def _loop(self) -> None:
        while self._running:
            try:
                sample: IMUSample = self._q.get(timeout=0.05)
            except queue.Empty:
                with self._lock:
                    self.state.paddle_velocity *= 0.85
                    self.state.launch = False
                    self.state.steer_left = False
                    self.state.steer_right = False
                    self.state.steer_up = False
                    self.state.steer_down = False
                    if (self._last_sample_time > 0
                            and time.monotonic() - self._last_sample_time > 3.0
                            and not self._disconnect_reported):
                        self.state.sensor_disconnected = True
                        self._disconnect_reported = True
                        logger.warning("No sensor data for 3 s — sensor may be disconnected")
                continue
            self._last_sample_time = time.monotonic()
            if self._disconnect_reported:
                with self._lock:
                    self.state.sensor_disconnected = False
                self._disconnect_reported = False
                logger.info("Sensor data resumed")
            self._process(sample)

    def _process(self, s: IMUSample) -> None:
        self._sync_config()
        cfg = self.config
        a = cfg.alpha

        # Legacy EMA for raw visualizer & spin
        self._smooth_ax = a * s.ax + (1 - a) * self._smooth_ax
        self._smooth_ay = a * s.ay + (1 - a) * self._smooth_ay
        self._smooth_az = a * s.az + (1 - a) * self._smooth_az
        self._smooth_gz = a * s.gz + (1 - a) * self._smooth_gz

        # Pause baseline adaptation while a hold gesture is arming (§4.3 & §7.4)
        self.frontend.adapt_paused = self._hold_x.arming or self._hold_y.arming

        # 1. Frontend: IMUSample → Frame (skips host Madgwick when hw quat valid)
        frame = self.frontend.process(s)
        self.buffer.append(frame)
        self._calibrated = frame.calibrated

        if not frame.calibrated:
            with self._lock:
                self.state.paddle_velocity = 0.0
                self.state.launch = False
                self.state.calibrated = False
                self._signals = self.frontend.signals()
            return

        # 2. Functional calibration (PCA swing window in seconds)
        if self._functional_calibrating:
            if self._functional_cal_t0 is None:
                self._functional_cal_t0 = frame.t
            self._functional_cal_buf.append(self.frontend.raw_tilt_g)
            elapsed = frame.t - self._functional_cal_t0
            cal_target = int(cfg.functional_cal_seconds * 100)
            if elapsed >= cfg.functional_cal_seconds or len(self._functional_cal_buf) >= cal_target:
                self.align_functional_axis(self._functional_cal_buf)
                with self._lock:
                    self._functional_calibrating = False
                    self.state.functional_calibrating = False
            else:
                with self._lock:
                    self.state.functional_calibrating = True

        # 3. Run detector plug-ins
        raw_events: List[GestureEvent] = []
        for d in self.detectors:
            raw_events.extend(d.update(frame))

        if cfg.spasm_gate_enabled:
            events = self.gate.filter(raw_events, self.buffer, frame.t)
        else:
            events = raw_events

        # 4. Map tilt (g-units) through dead-zone → legacy paddle_velocity & tilt_y
        tilt = frame.tilt_gx
        aligned_tilt_y = frame.tilt_gy
        thr = cfg.tilt_threshold
        t_max = cfg.tilt_max

        if abs(tilt) < thr:
            velocity = 0.0
        else:
            mag = min(1.0, (abs(tilt) - thr) / max(t_max - thr, 1e-6))
            velocity = mag if tilt > 0 else -mag

        if abs(aligned_tilt_y) < thr:
            tilt_y = 0.0
        else:
            mag_y = min(1.0, (abs(aligned_tilt_y) - thr) / max(t_max - thr, 1e-6))
            tilt_y = mag_y if aligned_tilt_y > 0 else -mag_y

        # 5. Spin from wrist twist (gz)
        gz = self._smooth_gz
        dead = cfg.twist_dead_zone
        if abs(gz) < dead:
            spin = 0.0
        else:
            spin = (gz - dead) / 200.0 if gz > 0 else (gz + dead) / 200.0
            spin = max(-1.0, min(1.0, spin))

        # 6. Derive legacy flags from detector events
        #    Direction-aware launch (§7.10): ONLY FLICK_UP launches (not downward jerks).
        launch = any(e.gesture is Gesture.FLICK_UP and e.detector == "flick" for e in events)
        if self.state.launch:
            launch = False

        steer_left = any(e.gesture is Gesture.FLICK_LEFT and e.detector == "steer" for e in events)
        steer_right = any(e.gesture is Gesture.FLICK_RIGHT and e.detector == "steer" for e in events)
        steer_up = any(e.gesture is Gesture.FLICK_UP and e.detector == "steer" for e in events)
        steer_down = any(e.gesture is Gesture.FLICK_DOWN and e.detector == "steer" for e in events)

        slice_ev = next((e for e in events if e.gesture is Gesture.SLICE), None)

        # Hold progress ring (whichever axis has higher progress)
        if self._hold_x.progress >= self._hold_y.progress:
            hold_prog, hold_dir = self._hold_x.progress, self._hold_x.direction
        else:
            hold_prog, hold_dir = self._hold_y.progress, self._hold_y.direction

        # Absolute Euler angles: hardware when valid, else Frontend's absolute quaternion
        if s.hw_fusion_valid:
            euler_roll = s.hw_roll
            euler_pitch = s.hw_pitch
            euler_yaw = s.hw_heading
        else:
            euler_roll, euler_pitch, euler_yaw = self.frontend.euler_abs

        qw, qx, qy, qz = self.frontend.q_abs

        # 7. Gesture-level auto-haptics removed: haptics are reserved for
        #    score celebrations and >30s rest reminders (in game_experience.py).

        # 8. Publish under lock
        with self._lock:
            self._events.extend(events)
            self._signals = self.frontend.signals(
                hold_progress=hold_prog, hold_direction=hold_dir
            )

            self.state.paddle_velocity = velocity
            self.state.launch = launch
            self.state.spin = spin
            self.state.tilt_y = tilt_y
            self.state.raw_ax = tilt
            self.state.raw_gz = gz
            self.state.calibrated = True
            self.state.abs_ax = self._smooth_ax
            self.state.abs_ay = self._smooth_ay
            self.state.abs_az = self._smooth_az
            self.state.abs_gx = s.gx
            self.state.abs_gy = s.gy
            self.state.abs_gz = s.gz
            self.state.qw = qw
            self.state.qx = qx
            self.state.qy = qy
            self.state.qz = qz
            self.state.euler_roll = euler_roll
            self.state.euler_pitch = euler_pitch
            self.state.euler_yaw = euler_yaw
            self.state.av_magnitude = frame.av_magnitude
            self.state.lin_ax = frame.lin_ax
            self.state.lin_ay = frame.lin_ay
            self.state.lin_az = frame.lin_az
            self.state.rel_roll = frame.roll
            self.state.rel_pitch = frame.pitch
            self.state.rel_yaw = frame.yaw
            self.state.hold_progress = hold_prog
            self.state.hold_direction = hold_dir
            self.state.slice_active = slice_ev is not None
            self.state.slice_direction = slice_ev.direction if slice_ev else ""
            self.state.combo_count = self._slice_det.combo_count_at(frame.t)
            self.state.steer_left = steer_left
            self.state.steer_right = steer_right
            self.state.steer_up = steer_up
            self.state.steer_down = steer_down

            if self._sensor is not None:
                self.state.mag_cal_state = self._sensor.mag_cal_state
            self.state.hw_heading = s.hw_heading
            self.state.hw_fusion_valid = s.hw_fusion_valid

        self._sample_count += 1
        if self._sample_count % 10 == 0:
            logger.debug(
                "tilt=%+.3fg  vel=%+.3f  gy=%+.1f°/s  launch=%s",
                tilt, velocity, s.gy, launch,
            )


# ── Keyboard fallback (used when no sensor is connected) ─────────────────────

class KeyboardFallback:
    """
    Mimics GestureInterpreter but maps keyboard state to GestureState, Signals
    and GestureEvents.  Allows the game to run without a physical sensor.
    """

    def __init__(self):
        self._left = False
        self._right = False
        self._launch = False
        self._events: deque = deque(maxlen=64)
        self._lock = threading.Lock()

    def press_left(self) -> None:
        with self._lock:
            self._left = True

    def press_right(self) -> None:
        with self._lock:
            self._right = True

    def release_left(self) -> None:
        with self._lock:
            self._left = False

    def release_right(self) -> None:
        with self._lock:
            self._right = False

    def trigger_launch(self) -> None:
        with self._lock:
            self._launch = True
            self._events.append(GestureEvent(Gesture.FLICK_UP, t=time.monotonic(), detector="keyboard"))

    def poll(self) -> List[GestureEvent]:
        with self._lock:
            out = list(self._events)
            self._events.clear()
            return out

    def signals(self) -> Signals:
        with self._lock:
            v = (-0.85 if self._left else 0.0) + (0.85 if self._right else 0.0)
            return Signals(tilt_x=v, tilt_y=0.0, pointer_x=0.5 * (1.0 + v), pointer_y=0.5, calibrated=True)

    def get_state(self) -> GestureState:
        with self._lock:
            v = (-0.85 if self._left else 0) + (0.85 if self._right else 0)
            launch = self._launch
            self._launch = False          # one-shot
            return GestureState(
                paddle_velocity=v,
                launch=launch,
                calibrated=True,
                tilt_y=0.0,
            )

    def vibrate(self, duration: float = 0.15) -> None: pass
    def save_calibration_to_nvm(self) -> None: pass
    def start(self) -> None: pass
    def stop(self) -> None: pass
