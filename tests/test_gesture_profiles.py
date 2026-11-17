"""
Unit tests for Phase 2: game-scoped detector profiles, locked-baseline tilt
(washout_enabled=False), and Math Choice ASTRA single-paradigm control.
"""

import math
import queue
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import pygame

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.frontend import Frontend, FrontendConfig
from shared.gesture import GestureConfig, GestureInterpreter
from shared.gestures.types import Signals
from shared.sensor import IMUSample, StreamChannel


def _quat_from_roll_deg(deg: float):
    half = math.radians(deg) * 0.5
    return (math.cos(half), math.sin(half), 0.0, 0.0)


class TestLockedBaselineWashout(unittest.TestCase):
    def test_washout_disabled_prevents_rebase_on_rest_inversion(self):
        fe = Frontend(FrontendConfig(
            calibration_seconds=0.2,
            calibration_samples=20,
            washout_enabled=False,
            rom_left_deg=30.0,
            rom_right_deg=30.0,
        ))
        t = 0.0
        # 1. Calibrate flat at rest
        for _ in range(25):
            t += 0.01
            fe.process(IMUSample(
                timestamp=t, ax=0.0, ay=0.0, az=1.0,
                gx=0.0, gy=0.0, gz=0.0,
                hw_fusion_valid=True, hw_qw=1.0, hw_qx=0.0, hw_qy=0.0, hw_qz=0.0,
            ))
        self.assertTrue(fe.calibrated)

        # 2. Hold a 20-deg tilt steadily for 4 seconds (longer than adapt_still_tau_s=1.2s)
        qw, qx, qy, qz = _quat_from_roll_deg(20.0)
        for _ in range(400):
            t += 0.01
            f = fe.process(IMUSample(
                timestamp=t, ax=0.0, ay=0.34, az=0.94,
                gx=0.0, gy=0.0, gz=0.0,
                hw_fusion_valid=True, hw_qw=qw, hw_qx=qx, hw_qy=qy, hw_qz=qz,
            ))
        tilted_val = f.tilt_y
        self.assertGreater(abs(tilted_val), 0.4)

        # 3. Return to neutral — must read ~0.0, NOT inverted in the opposite direction
        for _ in range(80):
            t += 0.01
            f = fe.process(IMUSample(
                timestamp=t, ax=0.0, ay=0.0, az=1.0,
                gx=0.0, gy=0.0, gz=0.0,
                hw_fusion_valid=True, hw_qw=1.0, hw_qx=0.0, hw_qy=0.0, hw_qz=0.0,
            ))
        self.assertAlmostEqual(f.tilt_y, 0.0, delta=0.05)


class TestDetectorProfileAndSensorSubscription(unittest.TestCase):
    def test_set_and_reset_detector_profile(self):
        q = queue.Queue()
        mock_sensor = MagicMock()
        mock_sensor.sf_profile = "full"
        mock_sensor.mag_cal_state = 0

        interp = GestureInterpreter(q, GestureConfig(), sensor=mock_sensor)

        # Fruit Ninja profile: gyro-only detectors
        ch = interp.set_detector_profile({"slice", "any_move"}, washout_enabled=True)
        self.assertEqual(ch, StreamChannel.GYRO)
        self.assertEqual({d.name for d in interp.detectors}, {"slice", "any_move"})
        mock_sensor.set_subscriptions.assert_called_with(StreamChannel.GYRO)

        # Math Choice ASTRA profile: locked-baseline hold_x (quat-only)
        ch2 = interp.set_detector_profile({"hold_x"}, washout_enabled=False)
        self.assertEqual(ch2, StreamChannel.QUAT)
        self.assertFalse(interp.frontend.cfg.washout_enabled)
        self.assertEqual({d.name for d in interp.detectors}, {"hold_x"})
        mock_sensor.set_subscriptions.assert_called_with(StreamChannel.QUAT)

        # Reset restores all detectors + default subscriptions
        ch3 = interp.reset_profile()
        self.assertEqual(ch3, StreamChannel.DEFAULT_FULL)
        self.assertTrue(interp.frontend.cfg.washout_enabled)
        self.assertGreater(len(interp.detectors), 2)
        mock_sensor.set_subscriptions.assert_called_with(StreamChannel.DEFAULT_FULL)


class TestMathChoiceAstraSingleParadigm(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        cls.screen = pygame.Surface((800, 600))
        cls.clock = pygame.time.Clock()

    def test_astra_tilt_not_overridden_by_small_gyro_tremor(self):
        from games.math_choice.game import MathChoiceGame

        game = MathChoiceGame(self.screen, self.clock, debug=False, mode="accessible")
        mock_src = MagicMock()
        mock_src.poll.return_value = []
        # Simulate tremor gz=20 deg/s (> old 16 deg/s MOVE threshold) while tilting right
        mock_src.signals.return_value = Signals(tilt_x=0.5, tilt_y=0.0, gz=20.0, gy=0.0, calibrated=True)
        game.gesture_src = mock_src

        start_x = game.cursor_x
        game._update_controls(gs=MagicMock(), dt=0.05)
        self.assertEqual(game._active_input_mode, "TILT")
        self.assertGreater(game.cursor_x, start_x)


if __name__ == "__main__":
    unittest.main()
