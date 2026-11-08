"""
tests/test_youtube_control.py — Unit tests for Accessible YouTube TV Controller
"""

import unittest
from shared.gesture import GestureState
from shared.youtube_control import (
    YouTubeGestureController,
    parse_youtube_url,
)


class TestYouTubeControl(unittest.TestCase):
    def test_parse_youtube_url_variants(self):
        vid, pl = parse_youtube_url("https://www.youtube.com/watch?v=K4DyBUG242c")
        self.assertEqual(vid, "K4DyBUG242c")
        self.assertEqual(pl, "")

        vid, pl = parse_youtube_url("https://youtu.be/hFZFjoX2cGg?si=1234")
        self.assertEqual(vid, "hFZFjoX2cGg")

        vid, pl = parse_youtube_url("https://www.youtube.com/playlist?list=PL1234567890ABCDEF")
        self.assertEqual(vid, "")
        self.assertEqual(pl, "PL1234567890ABCDEF")

        vid, pl = parse_youtube_url("86YLFOog4GM")
        self.assertEqual(vid, "86YLFOog4GM")

    def test_excited_movement_blocked_until_3_step_combo(self):
        ctrl = YouTubeGestureController(username="test_kid_unit", mode="accessible", require_combo=True)
        ctrl.refresh_default_channels()
        ctrl.tts.enabled = False

        start_idx = ctrl.item_idx

        # 1. While watching (combo_step == 0), random excited left/right swipes or tilts must NOT skip video!
        gs_excited = GestureState(
            calibrated=True,
            steer_right=True,
            slice_active=True,
            slice_direction="right",
            paddle_velocity=0.9,
        )
        act = ctrl.update(gs_excited, dt=0.2)
        self.assertIsNone(act)
        self.assertEqual(ctrl.item_idx, start_idx)
        self.assertEqual(ctrl.combo_step, 0)

        # 2. Step 1: Upward flick (`launch=True`) while tilted unlocks into Step 1 (waiting for center)
        gs_unlock = GestureState(calibrated=True, launch=True, paddle_velocity=0.6)
        self.assertIsNone(ctrl.update(gs_unlock, dt=0.05))
        self.assertEqual(ctrl.combo_step, 1)

        # Still tilted -> cannot swipe yet until centered
        self.assertIsNone(ctrl.update(gs_excited, dt=0.05))
        self.assertEqual(ctrl.combo_step, 1)

        # 3. Step 2: Relax wrist to neutral center -> advances to Step 2 (ARMED)
        gs_center = GestureState(calibrated=True, paddle_velocity=0.0)
        self.assertIsNone(ctrl.update(gs_center, dt=0.05))
        self.assertEqual(ctrl.combo_step, 2)

        # 4. Step 3: Now a deliberate right swipe triggers "next" and re-locks into cooldown!
        gs_swipe_right = GestureState(calibrated=True, steer_right=True)
        act_final = ctrl.update(gs_swipe_right, dt=0.05)
        self.assertEqual(act_final, "next")
        self.assertNotEqual(ctrl.item_idx, start_idx)
        self.assertEqual(ctrl.combo_step, 0)
        self.assertGreater(ctrl.cooldown_rem, 3.0)

    def test_quit_request_bridge(self):
        ctrl = YouTubeGestureController(username="test_kid_unit", mode="accessible")
        self.assertFalse(ctrl.quit_requested)
        ctrl.request_quit()
        self.assertTrue(ctrl.quit_requested)


if __name__ == "__main__":
    unittest.main()
