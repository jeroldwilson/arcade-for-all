"""
Unit tests for Phase 5: DualArmDatasetLogger CSV output & GestureHUD dual-sensor 3D arc.
"""

import csv
import sys
import tempfile
import unittest
from pathlib import Path

import pygame

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.gesture import GestureState
from shared.gesture_hud import GestureHUD
from shared.recorder import DUAL_DATASET_COLUMNS, DualArmDatasetLogger


class TestDualArmDatasetLogger(unittest.TestCase):
    def test_writes_exact_columns_for_dual_and_single_sensor_rows(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "dual_log.csv"
            with DualArmDatasetLogger(csv_path) as logger:
                logger.log(
                    timestamp=1.25,
                    dual_sensor_active=True,
                    pos_xyz=(10.5, -3.2, 18.0),
                    wrist_q=(1.0, 0.0, 0.0, 0.0),
                    upper_q=(0.707, 0.0, 0.707, 0.0),
                    lin_acc=(0.02, -0.01, 0.05),
                    gesture_label="reach_up",
                )
                logger.log(
                    timestamp=1.27,
                    dual_sensor_active=False,
                    pos_xyz=(0.0, 0.0, 0.0),
                    wrist_q=(0.9, 0.1, 0.0, 0.0),
                    upper_q=None,
                    lin_acc=(0.0, 0.0, 0.0),
                    gesture_label="idle",
                )

            with csv_path.open("r", encoding="utf-8") as fh:
                rows = list(csv.reader(fh))

            self.assertEqual(rows[0], DUAL_DATASET_COLUMNS)
            self.assertEqual(len(rows), 3)
            self.assertEqual(rows[1][1], "True")
            self.assertEqual(rows[1][2:5], ["10.5", "-3.2", "18.0"])
            self.assertEqual(rows[1][-1], "reach_up")
            self.assertEqual(rows[2][1], "False")
            self.assertEqual(rows[2][9:13], ["0.0", "0.0", "0.0", "0.0"])
            self.assertEqual(rows[2][-1], "idle")


class TestGestureHUDDualTrajectory(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()

    def test_draw_dual_sensor_arc_and_single_sensor_fallback(self):
        screen = pygame.Surface((400, 400))
        hud = GestureHUD(scale=0.3)

        gs_dual = GestureState(dual_sensor_active=True, pos_x=5.0, pos_y=2.0, pos_z=12.0)
        hud.draw(screen, gs_dual, 200, 200)
        gs_dual2 = GestureState(dual_sensor_active=True, pos_x=15.0, pos_y=4.0, pos_z=20.0)
        hud.draw(screen, gs_dual2, 200, 200)
        self.assertEqual(len(hud._traj_3d), 2)

        gs_single = GestureState(dual_sensor_active=False, euler_roll=15.0)
        hud.draw(screen, gs_single, 200, 200)


if __name__ == "__main__":
    unittest.main()
