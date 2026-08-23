"""
gesture.py — Wrist-tilt gesture interpreter

Converts raw IMU samples from the MetaMotion sensor into a simple
paddle-control signal consumed by the game engine.

Orientation & calibration
──────────────────────────
On startup the interpreter collects ~1 s of samples while the sensor is
at rest to measure the neutral gravity vector (calibration).  All tilt
measurements are relative to that baseline, so it doesn't matter which
way the sensor is physically mounted on the wrist.

Gesture mapping
───────────────
  Wrist tilted LEFT  → tilt < -tilt_threshold  →  MOVE LEFT
  Wrist tilted RIGHT → tilt > +tilt_threshold  →  MOVE RIGHT
  Wrist flat         → |tilt| < tilt_threshold  →  STOP

  Wrist flick UP (quick gy spike)             →  LAUNCH / POWER-SERVE
  Wrist twist CW  (gz positive)               →  CURVE RIGHT (ball spin)
  Wrist twist CCW (gz negative)               →  CURVE LEFT  (ball spin)

  Wrist tilted FORWARD → tilt_y < -tilt_threshold → UP (Snake)
  Wrist tilted BACK    → tilt_y > +tilt_threshold → DOWN (Snake)

All thresholds are adjustable via the GestureConfig dataclass.
"""

import logging
import time
import queue
import threading
import math
from collections import deque
from dataclasses import dataclass, field, replace
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

from shared.sensor import IMUSample
from shared.fusion_processor import FusionProcessor
from shared.gesture_detector import SliceDetector


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

    # Low-pass smoothing factor for gravity extraction [0–1].
    # Lower = heavier filtering = slower response but motion-noise immune.
    # 0.05 at 100 Hz ≈ 2 Hz cutoff: tracks slow tilts, ignores quick shakes.
    alpha: float = 0.05

    # Number of samples in the rolling window used for flick detection.
    # 6 samples = 60ms at 100Hz — catches shorter/sharper flicks (was 80ms).
    flick_window: int = 6

    # Dead-zone for gyro twist (°/s).
    twist_dead_zone: float = 30.0

    # Time (s) between repeated LAUNCH events to prevent accidental double-fire.
    launch_cooldown: float = 0.4

    # Samples collected for auto-calibration (≈1 s at 100 Hz).
    # Keep sensor still during this period.
    calibration_samples: int = 100

    # Minimum seconds between gesture triggers on each axis.
    # Used by game modules in accessible mode; GestureInterpreter ignores it.
    gesture_cooldown: float = 0.8

    # Functional alignment angle (radians).
    # Compensates for sensor being mounted twisted on the wrist or contractures in the arm.
    yaw_offset_rads: float = 0.0

    # Gyroscope magnitude (°/s) below which the adaptive baseline is allowed to
    # drift toward the current resting gravity vector.  Prevents adaptation during
    # active gestures while accommodating slow tremors.
    gyro_adapt_threshold: float = 45.0

    # Rate at which the adaptive baseline is dragged toward the current resting
    # gravity vector each sample.  0.002 at 100 Hz ≈ 5 s to fully adapt.
    adapt_rate: float = 0.002

    # Duration (seconds) of the functional-calibration data-collection window.
    # The user performs a natural arm swing for this long; PCA finds the axis.
    functional_cal_seconds: float = 2.5

    # Flick-to-steer mode (for Snake)
    flick_steer_enabled: bool = False
    flick_steer_threshold: float = 160.0  # °/s, lower than launch flick
    flick_steer_cooldown: float = 0.5     # seconds between directional flicks
    flick_steer_window: int = 7           # samples to check for peak


# Pre-defined configs for different game modes.
# The main application can select which config to pass to the GestureInterpreter.

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
    flick_steer_enabled=True
)

# ── Gesture state ─────────────────────────────────────────────────────────────

@dataclass
class GestureState:
    """
    Published to the game on every update tick.

    paddle_velocity : float  [-1.0 … +1.0]
        Negative = move left, positive = move right, 0 = stationary.
        Magnitude encodes speed (gentle tilt → slow, extreme tilt → fast).

    launch : bool
        True for exactly one frame when a LAUNCH flick is detected.

    spin : float  [-1.0 … +1.0]
        Wrist rotation mapped to ball spin hint.
        Negative = curve left, positive = curve right.

    tilt_y : float  [-1.0 … +1.0]
        Forward/back tilt (ay axis relative to calibrated neutral).
        Negative = wrist tilted forward (→ UP in Snake).
        Positive = wrist tilted back    (→ DOWN in Snake).

    raw_ax : float  — tilt value relative to calibrated neutral (for debug HUD)
    raw_gz : float  — smoothed gyroscope Z (for debug HUD)
    calibrated : bool  — False while collecting calibration samples

    abs_ax : float  — smoothed absolute accelerometer ax (g) — for calibration view
    abs_ay : float  — smoothed absolute accelerometer ay (g)
    abs_az : float  — smoothed absolute accelerometer az (g)
    abs_gx : float  — raw gyro gx (°/s)
    abs_gy : float  — raw gyro gy (°/s)
    abs_gz : float  — raw gyro gz (°/s)

    Sensor Fusion (Madgwick AHRS):
    qw, qx, qy, qz : float  — quaternion representing orientation
    euler_roll : float  — degrees, rotation around x-axis (stable via gravity)
    euler_pitch : float  — degrees, rotation around y-axis (stable via gravity)
    euler_yaw : float  — degrees, rotation around z-axis (drifts without magnetometer)
    av_magnitude : float  — total angular velocity magnitude (°/s)

    Slice Gesture Detection:
    slice_active : bool  — True if a slice gesture was detected this frame
    slice_direction : str  — direction of slice ("left"/"right"/"up"/"down"/"diagonal_*")
    combo_count : int  — number of slices detected within the last 1.5 seconds

    Flick-to-steer (for Snake):
    steer_left : bool  — True for one frame on a leftward flick
    steer_right : bool — True for one frame on a rightward flick
    steer_up : bool    — True for one frame on a forward flick
    steer_down : bool  — True for one frame on a backward flick
    """
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
    # Sensor fusion (Madgwick filter)
    qw: float = 1.0
    qx: float = 0.0
    qy: float = 0.0
    qz: float = 0.0
    euler_roll: float = 0.0
    euler_pitch: float = 0.0
    euler_yaw: float = 0.0
    av_magnitude: float = 0.0
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
    # Bosch Kalman Filter hardware outputs (drift-free when hw_fusion_valid=True)
    hw_heading: float = 0.0        # compass heading 0-360° (absolute, drift-free yaw)
    hw_fusion_valid: bool = False  # True once hardware fusion data is arriving
    # True after ~3 s of no samples — games can show a "sensor disconnected" overlay
    sensor_disconnected: bool = False


# ── Main interpreter ──────────────────────────────────────────────────────────

class GestureInterpreter:
    """
    Runs in its own thread, draining the sensor queue and maintaining
    the latest GestureState.  The game reads `interpreter.state` each frame.

    Calibration happens automatically during the first ~1 s: hold the sensor
    in the neutral (rest) wrist position while the LED is first turning green.
    """

    def __init__(
        self,
        sensor_queue: queue.Queue,
        config: Optional[GestureConfig] = None,
        sensor=None,
    ):
        self._q        = sensor_queue
        self.config    = config or GestureConfig()
        self.state     = GestureState()
        self.sensor    = sensor
        self._lock     = threading.Lock()

        # Gravity-extraction low-pass filter — all 3 axes
        self._smooth_ax: float = 0.0
        self._smooth_ay: float = 0.0
        self._smooth_az: float = 0.0
        self._smooth_gz: float = 0.0

        # Calibrated neutral gravity vector
        self._cal_ax: float = 0.0
        self._cal_ay: float = 0.0
        self._cal_az: float = 0.0
        self._calibrated: bool = False
        # Accumulation buffer for calibration samples (capped to prevent unbounded growth)
        self._cal_buf: deque = deque(maxlen=2 * self.config.calibration_samples)

        self._functional_calibrating: bool = False
        self._functional_cal_buf: List[Tuple[float, float]] = []

        # Rolling window for flick detection (stores recent gy samples)
        self._gy_window: deque = deque(maxlen=self.config.flick_window) # For launch
        # Windows for flick-to-steer
        self._gx_steer_window: deque = deque(maxlen=self.config.flick_steer_window)
        self._gy_steer_window: deque = deque(maxlen=self.config.flick_steer_window)


        self._last_steer_time: float = 0.0
        self._last_launch_time: float = 0.0
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._sample_count: int = 0
        # Disconnect detection: track time of last received sample
        self._last_sample_time: float = 0.0
        self._disconnect_reported: bool = False

        # Optional sensor reference for mag calibration polling
        self._sensor = sensor
        self._mag_cal_poll_next: float = 0.0

        # Sensor fusion and slice detection
        self._fusion: FusionProcessor = FusionProcessor()
        self._slice: SliceDetector = SliceDetector()
        self._last_ts: float = 0.0

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def start(self) -> None:
        self._running = True
        self._thread  = threading.Thread(
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
            self._calibrated = False
            self._cal_buf.clear()
            self.state.calibrated = False
        logger.info("Recalibration started — hold sensor still…")

    def start_functional_calibration(self) -> None:
        """Triggers a functional_cal_seconds window to learn the natural swing axis."""
        with self._lock:
            self._functional_calibrating = True
            self._functional_cal_buf.clear()
        logger.info("Functional calibration started — swing left and right…")

    def align_functional_axis(self, tilt_samples: List[Tuple[float, float]]) -> None:
        """
        Phase 4: Medical-Grade Functional Calibration (PCA).
        Takes a list of raw (tilt_x, tilt_y) points from a natural arm motion,
        finds the primary axis of motion, and rotates the coordinates to match it.
        """
        n = len(tilt_samples)
        if n < 10:
            return
            
        mean_x = sum(v[0] for v in tilt_samples) / n
        mean_y = sum(v[1] for v in tilt_samples) / n
        
        cxx = sum((v[0] - mean_x)**2 for v in tilt_samples)
        cxy = sum((v[0] - mean_x)*(v[1] - mean_y) for v in tilt_samples)
        cyy = sum((v[1] - mean_y)**2 for v in tilt_samples)
        
        if cxx == cyy and cxy == 0:
            return
            
        angle = 0.5 * math.atan2(2 * cxy, cxx - cyy)
        with self._lock:
            self.config.yaw_offset_rads = angle
        logger.info("PCA Functional Calibration: Rotated axes by %.1f°", math.degrees(angle))

    def get_state(self) -> GestureState:
        """Thread-safe snapshot of the latest gesture state."""
        with self._lock:
            return replace(self.state)

    # ── Processing loop ────────────────────────────────────────────────────────

    def _loop(self) -> None:
        while self._running:
            try:
                sample: IMUSample = self._q.get(timeout=0.05)
            except queue.Empty:
                # No new data — decay velocity toward zero to prevent drift
                with self._lock:
                    self.state.paddle_velocity *= 0.85
                    self.state.launch = False
                    self.state.steer_left = False
                    self.state.steer_right = False
                    self.state.steer_up = False
                    self.state.steer_down = False
                    # Disconnect detection: report after 3 s of silence
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
        cfg = self.config
        a   = cfg.alpha

        # ── Gravity-extraction low-pass filter (all 3 axes) ────────────────
        # Low alpha (0.05) means only very slow changes pass through —
        # exactly what we want: gravity is DC, motion acceleration is AC.
        self._smooth_ax = a * s.ax + (1 - a) * self._smooth_ax
        self._smooth_ay = a * s.ay + (1 - a) * self._smooth_ay
        self._smooth_az = a * s.az + (1 - a) * self._smooth_az
        self._smooth_gz = a * s.gz + (1 - a) * self._smooth_gz

        # ── Medical-Grade Adaptive Baseline (Washout Filter) ───────────────
        # Instead of a strict 1-second static calibration, we continuously
        # drag the baseline toward the current position VERY slowly.
        # This accommodates children who cannot hold still, and adapts if
        # their resting posture changes due to fatigue or spasticity.
        if not self._calibrated:
            self._cal_buf.append((self._smooth_ax, self._smooth_ay, self._smooth_az))
            if len(self._cal_buf) >= cfg.calibration_samples:
                # Use median instead of mean to ignore large tremor spikes
                sorted_ax = sorted(v[0] for v in self._cal_buf)
                sorted_ay = sorted(v[1] for v in self._cal_buf)
                sorted_az = sorted(v[2] for v in self._cal_buf)
                
                n = len(self._cal_buf)
                self._cal_ax = sorted_ax[n // 2]
                self._cal_ay = sorted_ay[n // 2]
                self._cal_az = sorted_az[n // 2]
                self._calibrated = True
                self._cal_buf.clear()
                logger.info(
                    "Calibrated — neutral gravity: ax=%+.3f  ay=%+.3f  az=%+.3f g",
                    self._cal_ax, self._cal_ay, self._cal_az
                )
            with self._lock:
                self.state.paddle_velocity = 0.0
                self.state.launch = False
                self.state.calibrated = False
            return
        else:
            # Continuous adaptation: if they are relatively still (not actively
            # swiping), slowly pull the baseline to their current resting state.
            gyro_mag = math.sqrt(s.gx**2 + s.gy**2 + s.gz**2)
            if gyro_mag < cfg.gyro_adapt_threshold:  # Allow for tremors, but ignore big swipes
                # adapt_rate at 100 Hz ≈ 5 s to fully adapt to a new resting posture.
                ar = cfg.adapt_rate
                self._cal_ax = ar * self._smooth_ax + (1 - ar) * self._cal_ax
                self._cal_ay = ar * self._smooth_ay + (1 - ar) * self._cal_ay
                self._cal_az = ar * self._smooth_az + (1 - ar) * self._cal_az

        # ── Tilt from gravity vector relative to calibrated neutral ────────
        # When the wrist tilts sideways, lateral gravity (ax) increases while
        # vertical gravity (az) decreases.  Subtracting the neutral ax gives
        # the pure tilt component, independent of sensor mounting orientation.
        raw_tilt_x = self._smooth_ax - self._cal_ax
        raw_tilt_y = self._smooth_ay - self._cal_ay
        
        # Phase 4: Functional Calibration data collection
        if self._functional_calibrating:
            self._functional_cal_buf.append((raw_tilt_x, raw_tilt_y))
            cal_target = int(cfg.functional_cal_seconds * 100)  # samples @ ~100 Hz
            if len(self._functional_cal_buf) >= cal_target:
                self.align_functional_axis(self._functional_cal_buf)
                with self._lock:
                    self._functional_calibrating = False
                    self.state.functional_calibrating = False
            else:
                with self._lock:
                    self.state.functional_calibrating = True

        # Phase 4: Apply functional alignment rotation (PCA)
        # This aligns the physical motion axis with the game's X/Y axis
        cos_off = math.cos(cfg.yaw_offset_rads)
        sin_off = math.sin(cfg.yaw_offset_rads)
        
        tilt = raw_tilt_x * cos_off + raw_tilt_y * sin_off
        aligned_tilt_y = -raw_tilt_x * sin_off + raw_tilt_y * cos_off

        thr   = cfg.tilt_threshold
        t_max = cfg.tilt_max

        if abs(tilt) < thr:
            velocity = 0.0
        else:
            # Map [thr … t_max] → [0 … 1], clamp at 1
            magnitude = (abs(tilt) - thr) / max(t_max - thr, 1e-6)
            magnitude = min(magnitude, 1.0)
            velocity  = magnitude if tilt > 0 else -magnitude

        # ── Forward/back tilt (ay axis) for Snake up/down control ─────────
        tilt_y_raw = aligned_tilt_y
        if abs(tilt_y_raw) < thr:
            tilt_y = 0.0
        else:
            magnitude_y = (abs(tilt_y_raw) - thr) / max(t_max - thr, 1e-6)
            magnitude_y = min(magnitude_y, 1.0)
            tilt_y = magnitude_y if tilt_y_raw > 0 else -magnitude_y

        # ── Flick detection for LAUNCH ─────────────────────────────────────
        # Sharp spike in gy (pitch axis) = flick upward.
        self._gy_window.append(s.gy)
        launch = False
        if len(self._gy_window) == cfg.flick_window:
            peak = max(abs(v) for v in self._gy_window)
            now  = time.monotonic()
            if (
                peak > cfg.flick_threshold
                and now - self._last_launch_time > cfg.launch_cooldown
            ):
                launch = True
                self._last_launch_time = now

        # ── Flick-to-steer detection (Snake) ───────────────────────────────
        # Sharp spike in gx (roll axis) = left/right flick.
        # Sharp spike in gy (pitch axis) = forward/back flick.
        steer_left = steer_right = steer_up = steer_down = False
        if cfg.flick_steer_enabled:
            self._gx_steer_window.append(s.gx)
            self._gy_steer_window.append(s.gy)
            now = time.monotonic()
            if now - self._last_steer_time > cfg.flick_steer_cooldown:
                # Check X-axis (roll) for left/right steering
                if len(self._gx_steer_window) == cfg.flick_steer_window:
                    gx_peak = max(self._gx_steer_window, key=abs)
                    if abs(gx_peak) > cfg.flick_steer_threshold:
                        if gx_peak > 0:
                            steer_right = True
                        else:
                            steer_left = True
                        self._last_steer_time = now

                # Check Y-axis (pitch) for up/down steering (if no X-flick)
                if not (steer_left or steer_right):
                    if len(self._gy_steer_window) == cfg.flick_steer_window:
                        gy_peak = max(self._gy_steer_window, key=abs)
                        if abs(gy_peak) > cfg.flick_steer_threshold:
                            # Pitch forward (nose down) = negative gy
                            if gy_peak < 0:
                                steer_up = True
                            else:
                                steer_down = True
                            self._last_steer_time = now

        # Reset launch flag after one frame
        if self.state.launch:
            launch = False

        # ── Spin from wrist twist (gz) ─────────────────────────────────────
        gz   = self._smooth_gz
        dead = cfg.twist_dead_zone
        if abs(gz) < dead:
            spin = 0.0
        else:
            spin = (gz - dead) / 200.0 if gz > 0 else (gz + dead) / 200.0
            spin = max(-1.0, min(1.0, spin))

        # ── Sensor fusion & slice detection ──────────────────────────────
        now_ts = s.timestamp
        dt_fusion = (now_ts - self._last_ts) if self._last_ts > 0 else 0.01
        self._last_ts = now_ts

        fusion_state = self._fusion.process(s, dt_fusion)
        slice_event  = self._slice.update(s.gx, s.gy, s.gz, t=now_ts)

        # Use Bosch Kalman Filter Euler angles when hardware fusion is active;
        # fall back to software Madgwick (roll/pitch stable, yaw drifts without mag).
        if s.hw_fusion_valid:
            euler_roll  = s.hw_roll
            euler_pitch = s.hw_pitch
            euler_yaw   = s.hw_heading   # compass heading — absolute, drift-free
        else:
            euler_roll  = fusion_state.euler_roll_deg
            euler_pitch = fusion_state.euler_pitch_deg
            euler_yaw   = fusion_state.euler_yaw_deg

        # ── Publish ────────────────────────────────────────────────────────
        with self._lock:
            self.state.paddle_velocity = velocity
            self.state.launch          = launch
            self.state.spin            = spin
            self.state.tilt_y          = tilt_y
            self.state.raw_ax          = tilt   # calibration-relative for HUD
            self.state.raw_gz          = gz
            self.state.calibrated      = True
            # Absolute IMU values for calibration visualizer
            self.state.abs_ax          = self._smooth_ax
            self.state.abs_ay          = self._smooth_ay
            self.state.abs_az          = self._smooth_az
            self.state.abs_gx          = s.gx
            self.state.abs_gy          = s.gy
            self.state.abs_gz          = s.gz
            # Sensor fusion outputs (hardware when available, software fallback)
            self.state.qw              = fusion_state.qw
            self.state.qx              = fusion_state.qx
            self.state.qy              = fusion_state.qy
            self.state.qz              = fusion_state.qz
            self.state.euler_roll      = euler_roll
            self.state.euler_pitch     = euler_pitch
            self.state.euler_yaw       = euler_yaw
            self.state.av_magnitude    = fusion_state.av_magnitude
            # Slice detection outputs
            self.state.slice_active    = slice_event is not None
            self.state.slice_direction = slice_event.direction if slice_event else ""
            self.state.combo_count     = self._slice.combo_count
            # Flick-to-steer outputs
            self.state.steer_left      = steer_left
            self.state.steer_right     = steer_right
            self.state.steer_up        = steer_up
            self.state.steer_down      = steer_down

            # Mirror sensor state passively — never send BLE commands from this thread.
            if self._sensor is not None:
                self.state.mag_cal_state   = self._sensor.mag_cal_state
            self.state.hw_heading      = s.hw_heading
            self.state.hw_fusion_valid = s.hw_fusion_valid

        # Log every 10th sample at DEBUG level (~10 Hz at 100 Hz sensor rate)
        self._sample_count += 1
        if self._sample_count % 10 == 0:
            logger.debug(
                "tilt=%+.3fg  vel=%+.3f  gy=%+.1f°/s  launch=%s",
                tilt, velocity, s.gy, launch
            )


# ── Keyboard fallback (used when no sensor is connected) ─────────────────────

class KeyboardFallback:
    """
    Mimics GestureInterpreter but maps keyboard state to GestureState.
    Allows the game to run without a physical sensor for testing.
    """

    def __init__(self):
        self._left   = False
        self._right  = False
        self._launch = False
        self._lock   = threading.Lock()

    def press_left(self)     -> None:
        with self._lock: self._left = True
    def press_right(self)    -> None:
        with self._lock: self._right = True
    def release_left(self)   -> None:
        with self._lock: self._left = False
    def release_right(self)  -> None:
        with self._lock: self._right = False
    def trigger_launch(self) -> None:
        with self._lock: self._launch = True

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

    # Lifecycle stubs (no-ops for API compatibility)
    def start(self) -> None: pass
    def stop(self)  -> None: pass
