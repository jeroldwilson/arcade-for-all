"""
Unit tests for Phase 3: OneEuroFilter & 2-segment ArmKinematics2Seg Forward Kinematics.
All tests use deterministic synthetic quaternions — no second sensor required.
"""

import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.filters import OneEuroFilter
from shared.kinematics import ArmKinematics2Seg
from shared.quat import IDENTITY, q_from_euler


class TestOneEuroFilter(unittest.TestCase):
    def test_attenuates_high_freq_tremor_and_tracks_fast_step(self):
        filt = OneEuroFilter(min_cutoff=1.0, beta=0.05, d_cutoff=1.0)
        # 1. High-frequency tremor (10 Hz, amplitude 2.0) around 0.0
        outputs = []
        t = 0.0
        for i in range(100):
            t = i * 0.01
            tremor = 2.0 * math.sin(2.0 * math.pi * 10.0 * t)
            outputs.append(filt.update(tremor, t))
        # Peak after warmup should be significantly attenuated (< 0.6 vs 2.0)
        self.assertLess(max(abs(v) for v in outputs[30:]), 0.6)

        # 2. Fast intentional reach to 25.0 -> converges quickly
        for i in range(100, 150):
            t = i * 0.01
            val = filt.update(25.0, t)
        self.assertGreater(val, 22.0)


class TestArmKinematics2Seg(unittest.TestCase):
    def test_resting_pose_is_origin_and_calibrates_over_window(self):
        kin = ArmKinematics2Seg(upper_arm_cm=28.0, forearm_cm=25.0, calibration_seconds=2.0)
        t = 0.0
        for _ in range(25):
            st = kin.update(t, IDENTITY, IDENTITY)
            t += 0.1
        self.assertTrue(kin.calibrated)
        self.assertTrue(st.dual_sensor_active)
        self.assertAlmostEqual(st.pos_x, 0.0, places=5)
        self.assertAlmostEqual(st.pos_y, 0.0, places=5)
        self.assertAlmostEqual(st.pos_z, 0.0, places=5)

    def test_90_deg_elbow_flexion_displaces_forearm_only(self):
        kin = ArmKinematics2Seg(upper_arm_cm=28.0, forearm_cm=25.0, beta=0.5, min_cutoff=10.0)
        kin.set_resting_poses(IDENTITY, IDENTITY)

        # Pitch forearm 90 deg: [0, 0, -25] rotates to [-25, 0, 0] or [+25, 0, 0];
        # relative to resting [0, 0, -25], Z rises by +25 cm and horizontal moves by 25 cm.
        q_elbow_90 = q_from_euler(0.0, 90.0, 0.0)
        t = 0.0
        for _ in range(60):
            t += 0.02
            st = kin.update(t, q_wrist=q_elbow_90, q_upper=IDENTITY)

        self.assertTrue(st.dual_sensor_active)
        self.assertAlmostEqual(abs(st.pos_x), 25.0, delta=0.8)
        self.assertAlmostEqual(st.pos_y, 0.0, delta=0.5)
        self.assertAlmostEqual(st.pos_z, 25.0, delta=0.8)

    def test_90_deg_shoulder_elevation_moves_both_segments(self):
        kin = ArmKinematics2Seg(upper_arm_cm=28.0, forearm_cm=25.0, beta=0.5, min_cutoff=10.0)
        kin.set_resting_poses(IDENTITY, IDENTITY)

        q_90 = q_from_euler(90.0, 0.0, 0.0)
        t = 0.0
        for _ in range(60):
            t += 0.02
            st = kin.update(t, q_wrist=q_90, q_upper=q_90)

        # Both segments rotated 90 deg around X -> total arm length = 28 + 25 = 53 cm
        self.assertAlmostEqual(abs(st.pos_y), 53.0, delta=1.5)
        self.assertAlmostEqual(st.pos_z, 53.0, delta=1.5)

    def test_single_sensor_fallback_without_upper_arm(self):
        kin = ArmKinematics2Seg()
        kin.set_resting_poses(IDENTITY, IDENTITY)
        st = kin.update(0.1, q_wrist=IDENTITY, q_upper=None)
        self.assertFalse(st.dual_sensor_active)
        self.assertEqual((st.pos_x, st.pos_y, st.pos_z), (0.0, 0.0, 0.0))


if __name__ == "__main__":
    unittest.main()
