"""
games/scratch_pad/game.py — Scratch Pad to test gesture data

Draw lines, flip (flick) to toggle pen on/off, change colors,
and display matched gesture predictions from ML data.
"""

import math
import random
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

import pygame

from shared.gesture_learner import GestureLearningSystem, IMUSnapshot
from shared.learn_test_support import (
    draw_gesture_debug_overlay,
    draw_submode_indicator,
    draw_validation_panel,
)
from shared.gesture_hud import GestureHUD

# ── Constants ─────────────────────────────────────────────────────────────────
W, H = 800, 600
FPS = 60

# ── Colors ────────────────────────────────────────────────────────────────────
BG = (15, 15, 25)
TEXT_CLR = (255, 255, 255)
DIM_CLR = (180, 180, 200)

PALETTE = [
    (255, 100, 100), (100, 255, 100), (100, 100, 255),
    (255, 255, 100), (255, 100, 255), (100, 255, 255),
    (255, 165, 0), (200, 150, 255)
]

@dataclass
class LineSegment:
    points: List[Tuple[float, float]]
    color: Tuple[int, int, int]


class ScratchPadGame:
    def __init__(self, screen, clock, debug=False, mode="standard", audio=None, username=""):
        self._screen = screen
        self._clock = clock
        self._debug = debug
        self._mode = mode
        self._audio = audio
        self._username = username
        self.hud = GestureHUD("/Users/jerold/.gemini/antigravity-ide/brain/3c53c120-8bf4-4a05-a904-340edfef9b68/metamotion_kid_hand_flat_1788027714986.jpg", scale=0.3)
        self._gesture_src = None
        
        self._learning_system = GestureLearningSystem(username=username)

        self._init_layout(screen)
        self._reset()

    def _init_layout(self, screen):
        self._screen = screen
        self._W, self._H = screen.get_size()
        sc = min(self._W / W, self._H / H)
        self._sc = sc
        self._is_fullscreen = not (self._W == W and self._H == H)

        self._font_lg = pygame.font.SysFont("monospace", max(24, int(48 * sc)), bold=True)
        self._font_md = pygame.font.SysFont("monospace", max(16, int(28 * sc)), bold=True)
        self._font_sm = pygame.font.SysFont("monospace", max(10, int(16 * sc)))

    def _reset(self):
        self._cursor_x = self._W // 2
        self._cursor_y = self._H // 2
        self._pen_down = False
        self._lines: List[LineSegment] = []
        self._current_color = PALETTE[0]
        self._predicted_gesture = ""
        self._prediction_timer = 0.0

    def run(self, gesture_src):
        self._gesture_src = gesture_src
        self._reset()
        pygame.mouse.set_visible(False)
        if self._audio:
            self._audio.start_background()

        while True:
            dt = self._clock.tick(FPS) / 1000.0
            result = self._handle_events()
            if result:
                if self._audio: self._audio.stop_background()
                return result
            self._update(dt)
            self._draw()
            gs = self._gesture_src.get_state() if getattr(self, "_gesture_src", None) is not None else None
            if gs:
                self.hud.draw(self._screen, gs, self._W - 100, self._H - 100)
            pygame.display.flip()

    def _handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return "quit"
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    return "home"
                if event.key == pygame.K_f:
                    self._toggle_fullscreen()
                if event.key == pygame.K_d:
                    self._debug = not self._debug
                if event.key == pygame.K_c:
                    self._lines.clear()
        return None

    def _toggle_fullscreen(self):
        self._is_fullscreen = not self._is_fullscreen
        new_screen = pygame.display.set_mode((0, 0) if self._is_fullscreen else (W, H), pygame.FULLSCREEN if self._is_fullscreen else 0)
        self._init_layout(new_screen)

    def _update(self, dt):
        if self._prediction_timer > 0:
            self._prediction_timer -= dt

        gs = self._gesture_src.get_state() if self._gesture_src else None
        if gs and gs.calibrated:
            # Reconstruct IMUSnapshot and feed learning system
            snap = IMUSnapshot(
                t=time.monotonic(),
                gx=gs.abs_gx, gy=gs.abs_gy, gz=gs.abs_gz,
                ax=gs.abs_ax, ay=gs.abs_ay, az=gs.abs_az,
                euler_roll=gs.euler_roll, euler_pitch=gs.euler_pitch
            )
            self._learning_system.buffer.push(snap)
            
            # Make predictions periodically if we have enough buffer
            window = self._learning_system.buffer.snapshot()
            features = self._learning_system.extractor.extract(window)
            if features:
                direction, conf = self._learning_system.model.predict_with_confidence(features)
                if direction and conf >= self._learning_system.model.confidence_threshold:
                    self._predicted_gesture = f"{direction.upper()} ({conf*100:.0f}%)"
                    self._prediction_timer = 2.0  # display for 2 seconds

            # Map Euler angles directly to screen position for drawing
            max_angle = 30.0
            roll = max(-max_angle, min(max_angle, gs.euler_roll))
            pitch = max(-max_angle, min(max_angle, gs.euler_pitch))

            self._cursor_x = self._W * (roll + max_angle) / (2 * max_angle)
            self._cursor_y = self._H * (pitch + max_angle) / (2 * max_angle)

            # Check for flick to toggle pen
            if gs.launch:
                self._pen_down = not self._pen_down
                if self._pen_down:
                    self._current_color = random.choice(PALETTE)
                    self._lines.append(LineSegment(points=[], color=self._current_color))
                    if self._audio: self._audio.play_flick_cast()
                else:
                    if self._audio: self._audio.play_collect()

            # Add points to active line
            if self._pen_down:
                if not self._lines:
                    self._lines.append(LineSegment(points=[], color=self._current_color))
                
                last_line = self._lines[-1]
                # Avoid adding points if too close to previous point to smooth drawing
                if not last_line.points or math.hypot(self._cursor_x - last_line.points[-1][0], self._cursor_y - last_line.points[-1][1]) > 5 * self._sc:
                    last_line.points.append((self._cursor_x, self._cursor_y))

    def _draw(self):
        self._screen.fill(BG)

        # Draw lines
        for line in self._lines:
            if len(line.points) > 1:
                pygame.draw.lines(self._screen, line.color, False, line.points, int(4 * self._sc))
            elif len(line.points) == 1:
                pygame.draw.circle(self._screen, line.color, (int(line.points[0][0]), int(line.points[0][1])), int(4 * self._sc))

        # Draw cursor
        cursor_color = self._current_color if self._pen_down else (100, 100, 100)
        pygame.draw.circle(self._screen, cursor_color, (int(self._cursor_x), int(self._cursor_y)), int(10 * self._sc))
        if not self._pen_down:
            pygame.draw.circle(self._screen, (50, 50, 50), (int(self._cursor_x), int(self._cursor_y)), int(8 * self._sc))

        # Draw UI
        self._draw_ui()

        if self._debug and self._gesture_src:
            draw_gesture_debug_overlay(self._screen, self._gesture_src.get_state(), self._W, self._H, self._sc, self._font_sm)

    def _draw_ui(self):
        sc = self._sc
        title = self._font_md.render("Scratch Pad", True, TEXT_CLR)
        self._screen.blit(title, (int(20 * sc), int(20 * sc)))
        
        status = "PEN: ON" if self._pen_down else "PEN: OFF"
        status_surf = self._font_sm.render(status, True, self._current_color if self._pen_down else DIM_CLR)
        self._screen.blit(status_surf, (int(20 * sc), int(50 * sc)))

        inst = self._font_sm.render("Tilt to move  •  Flick UP to toggle pen  •  C to clear", True, DIM_CLR)
        self._screen.blit(inst, (int(20 * sc), self._H - int(30 * sc)))

        if self._prediction_timer > 0 and self._predicted_gesture:
            pred_surf = self._font_lg.render(f"Gesture: {self._predicted_gesture}", True, (255, 200, 100))
            self._screen.blit(pred_surf, pred_surf.get_rect(center=(self._W // 2, int(80 * sc))))
