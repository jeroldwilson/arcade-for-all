"""
kinematics.py — Optional 2-segment Forward Kinematics (Upper Arm + Forearm).

Biomechanical Model & Axis Alignment Assumptions
────────────────────────────────────────────────
1. Coordinate frame (resting-relative world frame):
   - Origin (0, 0, 0) is the child's natural resting wrist position captured
     during the 2–3 second Resting Calibration ("Zeroing") phase.
   - By default, both segments point along `-Z` in their resting posture
     (arm hanging comfortably downward at the child's side/lap):
       upper_rest_vec   = (0, 0, -UPPER_ARM_LENGTH_CM)
       forearm_rest_vec = (0, 0, -FOREARM_LENGTH_CM)
     (Callers may override `upper_rest_vec` / `forearm_rest_vec` if the child's
      resting posture is e.g. forearm resting forward along `+Y` on a tray.)
2. Relative rotation from resting pose:
   - Each IMU quaternion `q` rotates sensor-frame vectors into the world frame.
   - At rest, we average `q_upper_rest` and `q_wrist_rest`.
   - On every update frame, the world-frame rotation *away from rest* is:
       q_rel = q_current ⊗ q_rest⁻¹
     so `q_rel == IDENTITY` at rest, and rotating `rest_vec` by `q_rel` yields
     the displaced segment vector in world coordinates.
3. 2-Segment Forward Kinematics:
   - p_elbow = q_rotate(q_upper_rel, upper_rest_vec)
   - p_wrist_total = p_elbow + q_rotate(q_wrist_rel, forearm_rest_vec)
   - Subtracting `(upper_rest_vec + forearm_rest_vec)` shifts the origin so
     resting posture is exactly `(0, 0, 0)`.
4. Tremor smoothing:
   - `(pos_x, pos_y, pos_z)` is passed through a 3D One Euro Filter to suppress
     involuntary spastic tremors while keeping intentional diagonal reaches snappy.
5. Single-sensor fallback:
   - If `q_upper` is `None`, `dual_sensor_active` is `False` and `(0, 0, 0)` is
     returned without raising.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from shared.filters import OneEuroFilter3D
from shared.quat import IDENTITY, Quat, Vec3, q_average, q_conj, q_mul, q_normalize, q_rotate

UPPER_ARM_LENGTH_CM: float = 28.0
FOREARM_LENGTH_CM: float = 25.0
REST_CALIBRATION_SECONDS: float = 2.5


@dataclass(frozen=True)
class KinematicsState:
    pos_x: float = 0.0
    pos_y: float = 0.0
    pos_z: float = 0.0
    elbow_x: float = 0.0
    elbow_y: float = 0.0
    elbow_z: float = 0.0
    dual_sensor_active: bool = False
    calibrated: bool = False


class ArmKinematics2Seg:
    """Computes resting-origin 3D wrist position (cm) from upper-arm + wrist quats."""

    def __init__(
        self,
        upper_arm_cm: float = UPPER_ARM_LENGTH_CM,
        forearm_cm: float = FOREARM_LENGTH_CM,
        calibration_seconds: float = REST_CALIBRATION_SECONDS,
        upper_rest_vec: Optional[Vec3] = None,
        forearm_rest_vec: Optional[Vec3] = None,
        min_cutoff: float = 1.2,
        beta: float = 0.05,
    ):
        self.upper_arm_cm = float(upper_arm_cm)
        self.forearm_cm = float(forearm_cm)
        self.calibration_seconds = float(calibration_seconds)
        self.upper_rest_vec: Vec3 = upper_rest_vec or (0.0, 0.0, -self.upper_arm_cm)
        self.forearm_rest_vec: Vec3 = forearm_rest_vec or (0.0, 0.0, -self.forearm_cm)
        self._rest_origin: Vec3 = (
            self.upper_rest_vec[0] + self.forearm_rest_vec[0],
            self.upper_rest_vec[1] + self.forearm_rest_vec[1],
            self.upper_rest_vec[2] + self.forearm_rest_vec[2],
        )
        self._filter = OneEuroFilter3D(min_cutoff=min_cutoff, beta=beta)
        self.reset()

    def reset(self) -> None:
        self.calibrated: bool = False
        self.q_upper_rest: Quat = IDENTITY
        self.q_wrist_rest: Quat = IDENTITY
        self._cal_t0: Optional[float] = None
        self._cal_upper: List[Quat] = []
        self._cal_wrist: List[Quat] = []
        self._filter.reset()

    def set_resting_poses(self, q_wrist_rest: Sequence[float], q_upper_rest: Sequence[float]) -> None:
        self.q_wrist_rest = q_normalize(q_wrist_rest)
        self.q_upper_rest = q_normalize(q_upper_rest)
        self.calibrated = True
        self._cal_upper.clear()
        self._cal_wrist.clear()
        self._filter.reset()

    def update(
        self,
        t: float,
        q_wrist: Sequence[float],
        q_upper: Optional[Sequence[float]] = None,
    ) -> KinematicsState:
        if q_upper is None:
            return KinematicsState(dual_sensor_active=False, calibrated=self.calibrated)

        qw = q_normalize(q_wrist)
        qu = q_normalize(q_upper)

        if not self.calibrated:
            if self._cal_t0 is None:
                self._cal_t0 = float(t)
            self._cal_wrist.append(qw)
            self._cal_upper.append(qu)
            if (float(t) - self._cal_t0) >= self.calibration_seconds - 1e-9:
                self.set_resting_poses(q_average(self._cal_wrist), q_average(self._cal_upper))
            return KinematicsState(dual_sensor_active=True, calibrated=self.calibrated)

        # World-frame delta rotations away from the calibrated resting pose:
        #   q_rel = q_current ⊗ q_rest⁻¹
        q_upper_rel = q_normalize(q_mul(qu, q_conj(self.q_upper_rest)))
        q_wrist_rel = q_normalize(q_mul(qw, q_conj(self.q_wrist_rest)))

        p_elbow = q_rotate(q_upper_rel, self.upper_rest_vec)
        p_forearm = q_rotate(q_wrist_rel, self.forearm_rest_vec)

        raw_x = (p_elbow[0] + p_forearm[0]) - self._rest_origin[0]
        raw_y = (p_elbow[1] + p_forearm[1]) - self._rest_origin[1]
        raw_z = (p_elbow[2] + p_forearm[2]) - self._rest_origin[2]

        pos_x, pos_y, pos_z = self._filter.update(raw_x, raw_y, raw_z, t)
        return KinematicsState(
            pos_x=pos_x,
            pos_y=pos_y,
            pos_z=pos_z,
            elbow_x=p_elbow[0] - self.upper_rest_vec[0],
            elbow_y=p_elbow[1] - self.upper_rest_vec[1],
            elbow_z=p_elbow[2] - self.upper_rest_vec[2],
            dual_sensor_active=True,
            calibrated=True,
        )
