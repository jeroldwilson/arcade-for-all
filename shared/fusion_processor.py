"""
fusion_processor.py — Madgwick 6-DOF AHRS (sensor fusion) filter

Combines accelerometer and gyroscope to estimate orientation as a quaternion and Euler angles.
Uses gravity as the only reference vector — no magnetometer support.

Output:
  - Quaternion (qw, qx, qy, qz): numerically stable orientation representation
  - Euler angles (roll, pitch, yaw): ±90° gimbal lock free
  - Linear acceleration: gravity-removed accel for detecting slicing motion
  - Angular velocity magnitude: total rotation rate

Note: Roll and pitch are stable (gravity reference). Yaw drifts without magnetometer.
"""

import math
from dataclasses import dataclass


@dataclass
class FusionState:
    """Output of one sensor fusion iteration."""
    qw: float = 1.0         # quaternion w (scalar)
    qx: float = 0.0         # quaternion x
    qy: float = 0.0         # quaternion y
    qz: float = 0.0         # quaternion z
    euler_roll_deg: float = 0.0     # degrees (rotation around x-axis)
    euler_pitch_deg: float = 0.0    # degrees (rotation around y-axis)
    euler_yaw_deg: float = 0.0      # degrees (rotation around z-axis) — drifts without mag
    av_magnitude: float = 0.0       # total angular velocity magnitude (°/s)
    lin_ax: float = 0.0     # linear acceleration x (gravity-removed) (g)
    lin_ay: float = 0.0     # linear acceleration y (g)
    lin_az: float = 0.0     # linear acceleration z (g)


class MadgwickFilter:
    """
    6-DOF Madgwick AHRS filter (accel + gyro, no magnetometer).

    Iteratively estimates the quaternion that best aligns measured gravity
    (from accel) with the expected world-frame gravity vector [0, 0, 1].
    """

    BETA_DEFAULT = 0.033  # convergence rate; higher = faster but oscillates; 0.033 good for 100 Hz

    def __init__(self, beta: float = BETA_DEFAULT):
        """Initialize filter with identity quaternion."""
        self.beta = beta
        # Quaternion state: w is scalar, (x,y,z) is imaginary part
        self.qw = 1.0
        self.qx = 0.0
        self.qy = 0.0
        self.qz = 0.0

    def update(self, ax: float, ay: float, az: float,
               gx_rads: float, gy_rads: float, gz_rads: float,
               dt: float) -> None:
        """
        One Madgwick iteration.

        Args:
            ax, ay, az: accelerometer in g (any units, will be normalized)
            gx_rads, gy_rads, gz_rads: gyroscope in radians/second
            dt: elapsed time in seconds (clamped to [0.001, 0.1])
        """
        # Clamp dt to prevent large integration jumps or division issues
        dt = max(0.001, min(dt, 0.1))

        # ── Normalize accelerometer (detect free-fall and skip correction) ────
        accel_norm = math.sqrt(ax*ax + ay*ay + az*az)
        if accel_norm < 1e-6:
            # Free-fall or zero accel — skip gradient descent, just integrate gyro
            self._integrate_gyro(gx_rads, gy_rads, gz_rads, dt, gradient_norm=None)
            return

        ax_n = ax / accel_norm
        ay_n = ay / accel_norm
        az_n = az / accel_norm

        # ── Gradient descent: objective function (accel alignment error) ────
        # f(q) = [2(qx*qz - qw*qy) - ax_n,
        #         2(qw*qx + qy*qz) - ay_n,
        #         2(0.5 - qx² - qy²) - az_n]
        # This measures how far the rotated [0,0,1] gravity vector is from the measured accel.

        f0 = 2.0 * (self.qx * self.qz - self.qw * self.qy) - ax_n
        f1 = 2.0 * (self.qw * self.qx + self.qy * self.qz) - ay_n
        f2 = 2.0 * (0.5 - self.qx*self.qx - self.qy*self.qy) - az_n

        # ── Jacobian matrix J (3x4): partial derivatives of f w.r.t. [qw, qx, qy, qz] ────
        # J = [[-2*qy,   2*qz,  -2*qw,   2*qx],
        #      [ 2*qx,   2*qy,   2*qz,   2*qw],
        #      [    0,  -4*qx,  -4*qy,     0 ]]
        J00, J01, J02, J03 = -2*self.qy, 2*self.qz, -2*self.qw, 2*self.qx
        J10, J11, J12, J13 = 2*self.qx, 2*self.qy, 2*self.qz, 2*self.qw
        J20, J21, J22, J23 = 0.0, -4*self.qx, -4*self.qy, 0.0

        # ── Gradient = J^T @ f ────
        grad_w = J00*f0 + J10*f1 + J20*f2
        grad_x = J01*f0 + J11*f1 + J21*f2
        grad_y = J02*f0 + J12*f1 + J22*f2
        grad_z = J03*f0 + J13*f1 + J23*f2

        # ── Normalize gradient ────
        grad_norm_sq = grad_w*grad_w + grad_x*grad_x + grad_y*grad_y + grad_z*grad_z
        if grad_norm_sq > 1e-6:
            grad_norm = math.sqrt(grad_norm_sq)
            grad_w /= grad_norm
            grad_x /= grad_norm
            grad_y /= grad_norm
            grad_z /= grad_norm
        else:
            grad_w = grad_x = grad_y = grad_z = 0.0

        # ── Integrate with gyro correction ────
        self._integrate_gyro(gx_rads, gy_rads, gz_rads, dt,
                           gradient_norm=(grad_w, grad_x, grad_y, grad_z))

    def _integrate_gyro(self, gx_rads, gy_rads, gz_rads, dt, gradient_norm):
        """
        Gyro integration with optional gradient descent correction.

        Args:
            gradient_norm: tuple (gw, gx, gy, gz) of normalized gradient, or None to skip
        """
        # Quaternion derivative from gyro: q_dot = 0.5 * q ⊗ [0, gx, gy, gz]
        # where ⊗ is quaternion multiplication
        q_dot_w = 0.5 * (-self.qx * gx_rads - self.qy * gy_rads - self.qz * gz_rads)
        q_dot_x = 0.5 * (self.qw * gx_rads + self.qy * gz_rads - self.qz * gy_rads)
        q_dot_y = 0.5 * (self.qw * gy_rads - self.qx * gz_rads + self.qz * gx_rads)
        q_dot_z = 0.5 * (self.qw * gz_rads + self.qx * gy_rads - self.qy * gx_rads)

        # Gradient descent correction (if available)
        if gradient_norm is not None:
            gw, gx, gy, gz = gradient_norm
            q_dot_w -= self.beta * gw
            q_dot_x -= self.beta * gx
            q_dot_y -= self.beta * gy
            q_dot_z -= self.beta * gz

        # Integrate: q += q_dot * dt
        self.qw += q_dot_w * dt
        self.qx += q_dot_x * dt
        self.qy += q_dot_y * dt
        self.qz += q_dot_z * dt

        # Normalize quaternion
        q_norm_sq = self.qw*self.qw + self.qx*self.qx + self.qy*self.qy + self.qz*self.qz
        if q_norm_sq > 1e-6:
            q_norm = math.sqrt(q_norm_sq)
            self.qw /= q_norm
            self.qx /= q_norm
            self.qy /= q_norm
            self.qz /= q_norm
        else:
            # Degenerate — reset to identity
            self.qw, self.qx, self.qy, self.qz = 1.0, 0.0, 0.0, 0.0

    def get_quaternion(self) -> tuple:
        """Returns (qw, qx, qy, qz) — current orientation as normalized quaternion."""
        return (self.qw, self.qx, self.qy, self.qz)

    def get_euler_deg(self) -> tuple:
        """
        Convert quaternion to Euler angles (degrees).

        Returns (roll, pitch, yaw) in degrees.
        Roll:  rotation around x-axis (typically ±180°)
        Pitch: rotation around y-axis (±90°, gimbal lock at ±90°)
        Yaw:   rotation around z-axis (±180°, drifts without magnetometer)
        """
        # Standard conversion from quaternion to Euler angles
        # See: https://en.wikipedia.org/wiki/Conversion_between_quaternions_and_Euler_angles

        # Roll: atan2(2(qw*qx + qy*qz), 1 - 2(qx² + qy²))
        roll_rad = math.atan2(
            2.0 * (self.qw * self.qx + self.qy * self.qz),
            1.0 - 2.0 * (self.qx * self.qx + self.qy * self.qy)
        )

        # Pitch: asin(2(qw*qy - qz*qx))  — clamp to avoid numerical issues
        sin_pitch = 2.0 * (self.qw * self.qy - self.qz * self.qx)
        sin_pitch = max(-1.0, min(1.0, sin_pitch))  # clamp to [-1, 1]
        pitch_rad = math.asin(sin_pitch)

        # Yaw: atan2(2(qw*qz + qx*qy), 1 - 2(qy² + qz²))
        yaw_rad = math.atan2(
            2.0 * (self.qw * self.qz + self.qx * self.qy),
            1.0 - 2.0 * (self.qy * self.qy + self.qz * self.qz)
        )

        return (
            math.degrees(roll_rad),
            math.degrees(pitch_rad),
            math.degrees(yaw_rad)
        )

    def get_linear_accel(self, ax: float, ay: float, az: float) -> tuple:
        """
        Remove gravity component from raw accelerometer reading.

        Rotates the expected world-frame gravity [0, 0, g] into sensor frame using
        the current quaternion, then subtracts from the measured accel.

        Args:
            ax, ay, az: raw accelerometer in g

        Returns:
            (lin_ax, lin_ay, lin_az): gravity-removed acceleration in g
        """
        # Expected gravity in sensor frame = inverse-rotate world [0, 0, 1]
        # Inverse quaternion rotation: q_inv ⊗ v ⊗ q, where v = [0, 0, 0, g]
        # Simplified (since v only has z component):
        grav_x = 2.0 * (self.qx * self.qz - self.qw * self.qy)
        grav_y = 2.0 * (self.qw * self.qx + self.qy * self.qz)
        grav_z = 1.0 - 2.0 * (self.qx * self.qx + self.qy * self.qy)

        return (
            ax - grav_x,
            ay - grav_y,
            az - grav_z
        )


class FusionProcessor:
    """
    High-level wrapper around MadgwickFilter.

    Handles unit conversion (°/s → rad/s), sample rate adaptation, and
    returns a complete FusionState for easy consumption by games.
    """

    DEG_TO_RAD = math.pi / 180.0

    def __init__(self, beta: float = MadgwickFilter.BETA_DEFAULT):
        """Initialize with a Madgwick filter."""
        self._filter = MadgwickFilter(beta)

    def process(self, sample, dt: float) -> FusionState:
        """
        Process one IMU sample and return fusion state.

        Args:
            sample: IMUSample with fields ax, ay, az (g), gx, gy, gz (°/s)
            dt: elapsed seconds since last call (will be clamped to [0.001, 0.1])

        Returns:
            FusionState with quaternion, euler angles, linear accel, av_magnitude
        """
        # Convert gyro from degrees/second to radians/second
        gx_rad = sample.gx * self.DEG_TO_RAD
        gy_rad = sample.gy * self.DEG_TO_RAD
        gz_rad = sample.gz * self.DEG_TO_RAD

        # Run one Madgwick iteration
        self._filter.update(sample.ax, sample.ay, sample.az,
                           gx_rad, gy_rad, gz_rad, dt)

        # Extract outputs
        qw, qx, qy, qz = self._filter.get_quaternion()
        roll_deg, pitch_deg, yaw_deg = self._filter.get_euler_deg()
        lin_ax, lin_ay, lin_az = self._filter.get_linear_accel(
            sample.ax, sample.ay, sample.az)

        # Compute total angular velocity magnitude
        av_magnitude = math.sqrt(sample.gx**2 + sample.gy**2 + sample.gz**2)

        return FusionState(
            qw=qw, qx=qx, qy=qy, qz=qz,
            euler_roll_deg=roll_deg,
            euler_pitch_deg=pitch_deg,
            euler_yaw_deg=yaw_deg,
            av_magnitude=av_magnitude,
            lin_ax=lin_ax,
            lin_ay=lin_ay,
            lin_az=lin_az,
        )
