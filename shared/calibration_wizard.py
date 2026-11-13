"""
calibration_wizard.py — 5-step guided per-child calibration screen & feedback helpers
(roadmap §7.6, Phase 3 & Phase 8).

Steps (§7.6):
  1. Rest   (3–10 s) : capture neutral quaternion q_base & resting tremor RMS
  2. Reach  (4 s)    : tilt comfortably left/right/up/down → 90th-percentile ROM
  3. Swing  (3 s)    : natural arm swing → PCA movement axis θ
  4. Hold   (2 s)    : hold a comfortable tilt → hold_time = 0.6 × median hold
  5. React  (flash)  : move when screen flashes → reaction_time & cooldown

Also provides:
  • `draw_hold_progress_ring(surface, signals, ...)` — live progress ring while
    `HoldDetector` is in `ARMING` (§7.4 & Phase 8)
  • `FatigueTracker` — rolling session success-rate monitor (Phase 8)
"""

from __future__ import annotations

import math
import time
from collections import deque
from typing import List, Optional, Tuple

import pygame

from shared.child_profile import VALID_MOUNTS, ChildProfile
from shared.gestures.types import Frame, Signals
from shared.username_screen import ACCENT, BG, CARD_BG, DIM_CLR, TEXT_CLR, UsernameScreen


class FatigueTracker:
    """Rolling session fatigue monitor (roadmap Phase 8).

    Tracks successful vs missed interactions per minute and flags when recent
    success drops significantly below the player's early-session baseline so the
    game can offer a rest break or easier profile thresholds.
    """

    def __init__(self, window_s: float = 60.0, min_events: int = 6, drop_ratio: float = 0.65):
        self.window_s = window_s
        self.min_events = min_events
        self.drop_ratio = drop_ratio
        self._events: deque = deque()   # (t, success: bool)
        self._baseline_rate: Optional[float] = None

    def record(self, success: bool, now: Optional[float] = None) -> None:
        t = time.monotonic() if now is None else now
        self._events.append((t, bool(success)))
        while self._events and self._events[0][0] < t - self.window_s:
            self._events.popleft()
        if self._baseline_rate is None and len(self._events) >= self.min_events:
            self._baseline_rate = self.success_rate

    @property
    def success_rate(self) -> float:
        if not self._events:
            return 1.0
        return sum(1 for _, ok in self._events if ok) / len(self._events)

    @property
    def fatigue_detected(self) -> bool:
        if self._baseline_rate is None or len(self._events) < self.min_events:
            return False
        return self.success_rate < self._baseline_rate * self.drop_ratio


def draw_hold_progress_ring(
    surface: pygame.Surface,
    signals: Optional[Signals],
    center: Optional[Tuple[int, int]] = None,
    radius: int = 28,
) -> None:
    """Draw a visual hold-progress ring when a HoldDetector is ARMING (§7.4)."""
    if signals is None or signals.hold_progress <= 0.02:
        return
    w, h = surface.get_size()
    cx, cy = center if center is not None else (w - radius - 24, radius + 24)
    prog = max(0.0, min(1.0, signals.hold_progress))
    rect = pygame.Rect(cx - radius, cy - radius, radius * 2, radius * 2)
    pygame.draw.circle(surface, (30, 35, 55), (cx, cy), radius + 4)
    pygame.draw.circle(surface, (70, 85, 120), (cx, cy), radius, width=4)
    end_angle = math.pi / 2 - prog * 2 * math.pi
    pygame.draw.arc(surface, (80, 235, 155), rect, end_angle, math.pi / 2, 5)


class CalibrationWizard:
    """Interactive 5-step child calibration screen reusing UsernameScreen styling."""

    STEPS = (
        ("1 / 5  REST",   "Relax your hand comfortably at rest",            3.0),
        ("2 / 5  REACH",  "Tilt comfortably LEFT, RIGHT, UP and DOWN",      4.0),
        ("3 / 5  SWING",  "Swing naturally back and forth",                 3.0),
        ("4 / 5  HOLD",   "Tilt and HOLD steady in one direction",          2.5),
        ("5 / 5  REACT",  "Wait for the GREEN FLASH, then move quickly!",   3.0),
    )

    def __init__(self, screen: pygame.Surface, clock: pygame.time.Clock, username: str):
        self._screen = screen
        self._clock = clock
        self._username = username or "guest"
        self._W, self._H = screen.get_size()
        sc = min(self._W / 800.0, self._H / 600.0)
        self._sc = sc
        self._font_title = UsernameScreen._make_font(max(20, int(34 * sc)), bold=True)
        self._font_md = UsernameScreen._make_font(max(13, int(20 * sc)), bold=False)
        self._font_sm = UsernameScreen._make_font(max(10, int(15 * sc)), bold=False)
        self.profile = ChildProfile.load(self._username)
        self._mount_idx = (
            VALID_MOUNTS.index(self.profile.mount_location)
            if self.profile.mount_location in VALID_MOUNTS else 0
        )

    def run(self, gesture_src) -> ChildProfile:
        """Run the 5-step guided calibration and save the resulting ChildProfile."""
        step_idx = 0
        step_elapsed = 0.0
        step_frames: List[Frame] = []
        hold_start: Optional[float] = None
        hold_durations: List[float] = []
        flash_t: Optional[float] = None
        react_latencies: List[float] = []

        while step_idx < len(self.STEPS):
            dt = self._clock.tick(60) / 1000.0
            step_elapsed += dt
            title, prompt, duration = self.STEPS[step_idx]

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return self.profile
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        return self.profile
                    if event.key == pygame.K_m:
                        self._mount_idx = (self._mount_idx + 1) % len(VALID_MOUNTS)
                        self.profile.mount_location = VALID_MOUNTS[self._mount_idx]
                    if event.key == pygame.K_SPACE:
                        step_elapsed = duration  # skip to next step

            f = getattr(getattr(gesture_src, "frontend", None), "last_frame", None)
            if f is not None:
                step_frames.append(f)
                if step_idx == 3:  # Hold step
                    if abs(f.tilt_x) > 0.2 or abs(f.tilt_y) > 0.2:
                        if hold_start is None:
                            hold_start = f.t
                    elif hold_start is not None:
                        hold_durations.append(f.t - hold_start)
                        hold_start = None
                elif step_idx == 4:  # React step
                    if step_elapsed >= 1.0 and flash_t is None:
                        flash_t = f.t
                    elif flash_t is not None and not react_latencies and f.av_magnitude > 35.0:
                        react_latencies.append(max(0.1, f.t - flash_t))

            self._draw(title, prompt, min(1.0, step_elapsed / duration),
                       flash_active=(step_idx == 4 and step_elapsed >= 1.0))
            pygame.display.flip()

            if step_elapsed >= duration:
                if step_idx == 0:
                    self.profile.calibrate_rest(step_frames)
                elif step_idx == 1:
                    self.profile.calibrate_reach(step_frames)
                elif step_idx == 2:
                    self.profile.calibrate_swing(step_frames)
                elif step_idx == 3:
                    if hold_start is not None and step_frames:
                        hold_durations.append(step_frames[-1].t - hold_start)
                    self.profile.calibrate_hold(hold_durations or [1.0])
                elif step_idx == 4:
                    self.profile.calibrate_reaction(react_latencies or [0.35])
                step_idx += 1
                step_elapsed = 0.0
                step_frames.clear()

        self.profile.calibrated_profile = True
        self.profile.save()
        if hasattr(gesture_src, "apply_profile"):
            gesture_src.apply_profile(self.profile)
        return self.profile

    def _draw(self, title: str, prompt: str, progress: float, flash_active: bool = False) -> None:
        self._screen.fill((25, 95, 50) if flash_active else BG)
        w, h = self._W, self._H
        card = pygame.Rect(int(w * 0.1), int(h * 0.15), int(w * 0.8), int(h * 0.7))
        pygame.draw.rect(self._screen, CARD_BG, card, border_radius=16)
        pygame.draw.rect(self._screen, ACCENT, card, width=2, border_radius=16)

        t_surf = self._font_title.render(f"Calibrate Profile: {self._username}", True, ACCENT)
        self._screen.blit(t_surf, (w // 2 - t_surf.get_width() // 2, int(h * 0.20)))

        s_surf = self._font_md.render(title, True, TEXT_CLR)
        self._screen.blit(s_surf, (w // 2 - s_surf.get_width() // 2, int(h * 0.34)))

        p_surf = self._font_md.render(prompt, True, DIM_CLR)
        self._screen.blit(p_surf, (w // 2 - p_surf.get_width() // 2, int(h * 0.44)))

        bar_bg = pygame.Rect(int(w * 0.2), int(h * 0.58), int(w * 0.6), int(26 * self._sc))
        bar_fg = pygame.Rect(bar_bg.x, bar_bg.y, int(bar_bg.width * progress), bar_bg.height)
        pygame.draw.rect(self._screen, (45, 50, 75), bar_bg, border_radius=8)
        pygame.draw.rect(self._screen, ACCENT, bar_fg, border_radius=8)

        hint = f"[M] Mount: {self.profile.mount_location}   [SPACE] Next   [ESC] Cancel"
        h_surf = self._font_sm.render(hint, True, DIM_CLR)
        self._screen.blit(h_surf, (w // 2 - h_surf.get_width() // 2, int(h * 0.74)))

