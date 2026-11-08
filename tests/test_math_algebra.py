"""
tests/test_math_algebra.py — Unit tests for Cyber Math 2-Level Curriculum & Dynamic Algebra Progression
"""

import os
import unittest
import pygame

# Headless pygame for testing
os.environ["SDL_VIDEODRIVER"] = "dummy"
pygame.init()

from games.math_choice.game import (
    MathChoiceGame,
    generate_algebra_problem,
)


class TestMathAlgebra(unittest.TestCase):
    def setUp(self):
        self.screen = pygame.display.set_mode((800, 600))
        self.clock = pygame.time.Clock()

    def test_algebra_generator_clean_positive_integers(self):
        # Generate 60 random algebra equations and verify all solutions are clean integers > 0
        for _ in range(60):
            boss = (_ % 5 == 0)
            disp, spoken, x_ans, offsets = generate_algebra_problem(boss=boss, accessible=True)
            self.assertIsInstance(x_ans, int)
            self.assertGreater(x_ans, 0)
            self.assertTrue("x" in disp)
            self.assertTrue("=" in disp)
            self.assertTrue("x" in spoken)
            # Ensure distractors don't duplicate x
            valid_distractors = [x_ans + o for o in offsets if x_ans + o > 0 and o != 0]
            self.assertTrue(len(valid_distractors) > 0)
            for d in valid_distractors:
                self.assertNotEqual(d, x_ans)

    def test_auto_level_up_on_level1_streak(self):
        game = MathChoiceGame(self.screen, self.clock, username="Tester")
        game.tts.enabled = False
        self.assertEqual(game.level, 1)
        self.assertEqual(game.level1_streak, 0)

        threshold = game.level_up_threshold

        # Simulate consecutive correct answers on Level 1
        for i in range(threshold - 1):
            game.handle_correct("left" if game.left_ans == game.correct_answer else "right", (200, 300))
            self.assertEqual(game.level, 1)
            self.assertEqual(game.level1_streak, i + 1)

        # Final answer hits the threshold -> triggers LEVEL UP to Level 2 (Cyber Algebra)!
        game.handle_correct("left" if game.left_ans == game.correct_answer else "right", (200, 300))
        self.assertEqual(game.level, 2)
        self.assertEqual(game.level1_streak, 0)
        self.assertTrue("ALGEBRA" in game.feedback_headline)

    def test_manual_level_toggle_and_algebra_problem_generation(self):
        game = MathChoiceGame(self.screen, self.clock, username="Tester")
        game.tts.enabled = False

        # Switch to Level 2
        game.level = 2
        game.generate_problem(speak_now=False)

        self.assertTrue("x" in game.problem_text)
        self.assertGreater(game.correct_answer, 0)
        self.assertTrue(game.left_ans == game.correct_answer or game.right_ans == game.correct_answer)


if __name__ == "__main__":
    unittest.main()

