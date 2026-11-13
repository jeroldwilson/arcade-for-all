"""
quat.py — Small, dependency-free quaternion helpers.

Convention (same as the Madgwick filter in fusion_processor.py):
  q = (w, x, y, z) rotates sensor-frame vectors into the world frame,
  so world gravity [0, 0, 1] seen in the sensor frame is
      g_sensor = (2(xz − wy), 2(wx + yz), 1 − 2(x² + y²)).
"""

from __future__ import annotations

import math
from typing import Iterable, Sequence, Tuple

Quat = Tuple[float, float, float, float]
Vec3 = Tuple[float, float, float]

IDENTITY: Quat = (1.0, 0.0, 0.0, 0.0)


def q_normalize(q: Sequence[float]) -> Quat:
    w, x, y, z = q
    n = math.sqrt(w * w + x * x + y * y + z * z)
    if n < 1e-9:
        return IDENTITY
    return (w / n, x / n, y / n, z / n)


def q_conj(q: Sequence[float]) -> Quat:
    """Conjugate == inverse for unit quaternions."""
    w, x, y, z = q
    return (w, -x, -y, -z)


def q_mul(a: Sequence[float], b: Sequence[float]) -> Quat:
    """Hamilton product a ⊗ b."""
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return (
        aw * bw - ax * bx - ay * by - az * bz,
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
    )


def q_relative(q_base: Sequence[float], q: Sequence[float]) -> Quat:
    """q_rel = q_base⁻¹ ⊗ q  (identity at the neutral pose)."""
    return q_normalize(q_mul(q_conj(q_base), q))


def q_rotate(q: Sequence[float], v: Sequence[float]) -> Vec3:
    """Rotate vector v by quaternion q:  v' = q ⊗ (0, v) ⊗ q*."""
    p = q_mul(q_mul(q, (0.0, v[0], v[1], v[2])), q_conj(q))
    return (p[1], p[2], p[3])


def gravity_from_q(q: Sequence[float]) -> Vec3:
    """World 'up' [0,0,1] expressed in the sensor frame (≈ accelerometer at rest, in g)."""
    w, x, y, z = q
    return (
        2.0 * (x * z - w * y),
        2.0 * (w * x + y * z),
        1.0 - 2.0 * (x * x + y * y),
    )


def euler_from_q(q: Sequence[float]) -> Vec3:
    """(roll, pitch, yaw) in degrees, ZYX convention (matches MadgwickFilter.get_euler_deg)."""
    w, x, y, z = q
    roll = math.atan2(2.0 * (w * x + y * z), 1.0 - 2.0 * (x * x + y * y))
    sp = max(-1.0, min(1.0, 2.0 * (w * y - z * x)))
    pitch = math.asin(sp)
    yaw = math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))
    return (math.degrees(roll), math.degrees(pitch), math.degrees(yaw))


def q_from_euler(roll_deg: float, pitch_deg: float, yaw_deg: float = 0.0) -> Quat:
    """Inverse of euler_from_q (ZYX)."""
    cr, sr = math.cos(math.radians(roll_deg) / 2), math.sin(math.radians(roll_deg) / 2)
    cp, sp = math.cos(math.radians(pitch_deg) / 2), math.sin(math.radians(pitch_deg) / 2)
    cy, sy = math.cos(math.radians(yaw_deg) / 2), math.sin(math.radians(yaw_deg) / 2)
    return (
        cr * cp * cy + sr * sp * sy,
        sr * cp * cy - cr * sp * sy,
        cr * sp * cy + sr * cp * sy,
        cr * cp * sy - sr * sp * cy,
    )


def v_normalize(v: Sequence[float]) -> Vec3:
    n = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if n < 1e-9:
        return (0.0, 0.0, 1.0)
    return (v[0] / n, v[1] / n, v[2] / n)


def q_from_two_vectors(a: Sequence[float], b: Sequence[float]) -> Quat:
    """Shortest-arc rotation taking unit-direction a onto b (so q_rotate(q, a) ∥ b)."""
    a = v_normalize(a)
    b = v_normalize(b)
    d = a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
    if d < -0.999999:
        # 180°: rotate about any axis orthogonal to a
        axis = (1.0, 0.0, 0.0) if abs(a[0]) < 0.9 else (0.0, 1.0, 0.0)
        c = (a[1] * axis[2] - a[2] * axis[1],
             a[2] * axis[0] - a[0] * axis[2],
             a[0] * axis[1] - a[1] * axis[0])
        c = v_normalize(c)
        return (0.0, c[0], c[1], c[2])
    c = (a[1] * b[2] - a[2] * b[1],
         a[2] * b[0] - a[0] * b[2],
         a[0] * b[1] - a[1] * b[0])
    return q_normalize((1.0 + d, c[0], c[1], c[2]))


def q_average(quats: Iterable[Sequence[float]]) -> Quat:
    """Hemisphere-aligned normalised mean (good approximation for clustered rotations)."""
    acc = [0.0, 0.0, 0.0, 0.0]
    ref = None
    for q in quats:
        if ref is None:
            ref = q
        sign = 1.0 if (q[0] * ref[0] + q[1] * ref[1] + q[2] * ref[2] + q[3] * ref[3]) >= 0 else -1.0
        for i in range(4):
            acc[i] += sign * q[i]
    if ref is None:
        return IDENTITY
    return q_normalize(acc)

