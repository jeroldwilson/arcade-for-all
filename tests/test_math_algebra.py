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

    def test_optional_qwen_coach_tones_and_fallback(self):
        from shared.llm_coach import QwenCoach

        coach = QwenCoach(username="Jerold", enabled=False)
        # By default (and when LLM is not installed), get_feedback returns None so standard TTS is never overridden
        self.assertIsNone(coach.get_feedback("success", "7 × 8", "7 times 8", 56, streak=3))

        # Verify tone classification between random one-off slip ("random_miss") vs struggling/slow ("motivate")
        self.assertEqual(
            QwenCoach.classify_miss_tone(streak_before_miss=4, consecutive_misses=1, response_seconds=3.5),
            "random_miss",
        )
        self.assertEqual(
            QwenCoach.classify_miss_tone(streak_before_miss=0, consecutive_misses=2, response_seconds=4.0),
            "motivate",
        )
        self.assertEqual(
            QwenCoach.classify_miss_tone(streak_before_miss=1, consecutive_misses=1, response_seconds=15.0),
            "motivate",
        )

        # Verify formatting of middle-school LLM lines for all 3 tones
        h1, s1, sp1 = coach._format_for_hud(
            "Big brain move right there, Jerold!", "success", "2x + 3 = 11", "2 x plus 3 equals 11", 4, 3, "right", True
        )
        self.assertIn("BIG BRAIN MOVE", h1)
        self.assertIn("x = 4", s1)
        # Ensure "(AI Coach)" is NOT present in the HUD message text
        self.assertNotIn("(AI Coach)", s1)
        # Ensure no unicode star or non-ascii glyphs that render as tofu boxes
        self.assertNotIn("★", h1)
        self.assertTrue(all(ord(c) < 128 for c in h1))

        h2, s2, sp2 = coach._format_for_hud(
            "Almost had it, shake it off!", "random_miss", "5 × 6", "5 times 6", 30, 2, "left", False
        )
        self.assertIn("ALMOST HAD IT", h2)
        self.assertNotIn("(AI Coach)", s2)
        self.assertIn("Move left for 30", sp2)

        h3, s3, sp3 = coach._format_for_hud(
            "Take a deep breath, you are building real skill.", "motivate", "3x = 15", "3 x equals 15", 5, 0, "right", True
        )
        self.assertIn("TAKE A DEEP BREATH", h3)
        self.assertNotIn("(AI Coach)", s3)
        self.assertIn("Aim right for 5", sp3)

    def test_feedback_banner_bounds_and_tts_wait(self):
        game = MathChoiceGame(self.screen, self.clock, username="Jerold")
        game.tts.enabled = False

        # Set an intentionally extra long headline and subtext
        game.feedback_headline = "JEROLD IS TRULY A MATH ACE WITH A STELLAR UNSTOPPABLE WINNING STREAK"
        game.feedback_subtext = "5 × 7 = 35 • Streak x1!"
        game.feedback_type = "correct"
        game.feedback_color = (0, 255, 128)

        # Drawing should gracefully auto-scale and fit without error
        game._draw_feedback_banner()

        # Verify TTS speaking property
        self.assertFalse(game.tts.is_speaking)

        # Verify feedback wait loop: while TTS is speaking, feedback timer stays active
        game.tts.enabled = True
        game.handle_correct("left", (200, 300))
        self.assertTrue(game._pending_new_problem)
        self.assertGreater(game.feedback_timer, 0)
        game.tts.stop()


if __name__ == "__main__":
    unittest.main()

