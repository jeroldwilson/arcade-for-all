"""
Unit tests for Scrib3D-style Plot3DGame and game list cleanup.
"""

import sys
import unittest
from pathlib import Path

import pygame

sys.path.insert(0, str(Path(__file__).parent.parent))

import home
from games.plot_3d.game import Plot3DGame
from shared.gesture import GestureState
from shared.gestures.bindings import GAME_GESTURE_LEGENDS
from shared.gestures.types import Signals
from shared.quat import q_from_euler


class TestPlot3DGame(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        cls.screen = pygame.Surface((800, 600))
        cls.clock = pygame.time.Clock()

    def test_ignores_static_hand_tilts_and_draws_on_wrist_translation(self):
        game = Plot3DGame(self.screen, self.clock)
        gs_rest = GestureState(calibrated=True, qw=1.0, qx=0.0, qy=0.0, qz=0.0)
        game._rezero(gs_rest)
        self.assertEqual(game.cur_pos, (0.0, 0.0, 0.0))

        # 1. Pure hand tilt (orientation changes 45 deg, lin_acc == 0) -> pen stays at (0,0,0)
        q_tilt = q_from_euler(45.0, 30.0, 0.0)
        gs_tilt = GestureState(
            calibrated=True,
            qw=q_tilt[0], qx=q_tilt[1], qy=q_tilt[2], qz=q_tilt[3],
            lin_ax=0.0, lin_ay=0.0, lin_az=0.0,
        )
        for _ in range(30):
            game._update_position(gs_tilt, Signals(calibrated=True), dt=0.016)
        self.assertEqual(game.cur_pos, (0.0, 0.0, 0.0))

        # 2. Wrist moves upward (+Z) & sideways (+X) -> pen extrudes in 3D
        for _ in range(15):
            game._update_position(
                GestureState(calibrated=True, qw=1.0, lin_ax=0.25, lin_az=0.25),
                Signals(calibrated=True), dt=0.02,
            )
        self.assertGreater(game.cur_pos[0], 1.0)
        self.assertGreater(game.cur_pos[2], 1.0)

        # 3. Stopping zeroes velocity cleanly without runaway
        for _ in range(5):
            game._update_position(gs_rest, Signals(calibrated=True), dt=0.02)
        pos_settled = game.cur_pos
        for _ in range(20):
            game._update_position(gs_rest, Signals(calibrated=True), dt=0.02)
        self.assertEqual(game.cur_pos, pos_settled)

        game._draw_scene(Signals(calibrated=True))

    def test_removed_games_absent_and_plot_3d_registered(self):
        for removed in ("magic_wand", "villain_slicer", "scratch_pad"):
            self.assertNotIn(removed, home.GAMES)
            self.assertNotIn(removed, home.GAME_META)
            self.assertNotIn(removed, GAME_GESTURE_LEGENDS)
        self.assertIn("plot_3d", home.GAMES)
        self.assertIn("plot_3d", home.GAME_META)
        self.assertIn("plot_3d", GAME_GESTURE_LEGENDS)


if __name__ == "__main__":
    unittest.main()
