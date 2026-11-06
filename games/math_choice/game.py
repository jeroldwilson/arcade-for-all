"""
games/math_choice/game.py — Cyber Math Overdrive (Accessible Motion & Voice Math Game)

Features:
  • Multi-Modal Accessible Controls:
      - Movement gesture (gyro swing / slice / wave) toward Left or Right answer
      - 2D / Horizontal Gyro cursor movement + Wrist Tilt toward answer portals
      - Flick-to-steer left/right & Upward flick to instant-fire when hovering
      - ASTRA (Accessible) intent assist: tremor filtering, gentle magnetic pull,
        and forgiving dwell lock-in
      - Keyboard (Left/Right, A/D, 1/2, Space/Enter) & Mouse hover/click
  • Fullscreen Support (F key) with dynamic resolution-independent layout scaling
  • Teen-Engaging Sci-Fi Arcade Visuals ("CYBER MATH OVERDRIVE"):
      - 3D perspective Neon Cyber Horizon Grid + parallax StarField + NebulaBg
      - Rotating Holographic Reactor Core & every-5-streak Boss Mecha-Drones
      - Hexagonal Neon Answer Portals with charge arcs, orbiting nodes & shockwaves
      - Articulated Plasma Turret that aims at the player's motion reticle and fires
        high-energy laser beams with particle explosions
      - Rank progression (Cyber Cadet -> Quantum Legend) & operation mode selector
  • Built-in Text-to-Speech (TTS) & Personalized Username Appreciation/Motivation:
      - Reads math problems and Left/Right answer numbers aloud automatically
      - Speaks and displays warm, personalized praise with the player's username on success
      - Speaks and displays encouraging, confidence-building motivation with username on retry
"""

import math
import random
import shutil
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import List, Optional, Tuple

import pygame

from shared.gesture import CONFIG_ACCESSIBLE_FLICK_STEER, CONFIG_STANDARD
from shared.gesture_hud import GestureHUD
from shared.game_experience import (
    FireworksCelebration,
    GameExitAppreciationScreen,
    NebulaBg,
    StarField,
    make_glow,
)


# ── Color Palette ─────────────────────────────────────────────────────────────
BG_DARK        = (10, 14, 28)
NEON_CYAN      = (0, 235, 255)
NEON_MAGENTA   = (255, 55, 165)
NEON_ORANGE    = (255, 155, 45)
NEON_GREEN     = (60, 255, 130)
NEON_YELLOW    = (255, 230, 65)
NEON_PURPLE    = (185, 85, 255)
NEON_RED       = (255, 85, 95)
TEXT_WHITE     = (255, 255, 255)
TEXT_DIM       = (165, 180, 210)


# ── Non-blocking Text-To-Speech (TTS) Helper ──────────────────────────────────

class MathTTS:
    """
    Non-blocking Text-to-Speech helper using macOS `/usr/bin/say` (or `espeak`
    fallback on Linux) in a managed background subprocess so it never blocks
    the 60 FPS pygame loop.
    """

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._lock = threading.Lock()
        self._proc: Optional[subprocess.Popen] = None
        self._say_bin = shutil.which("say")
        self._espeak_bin = shutil.which("espeak") or shutil.which("espeak-ng")

    @property
    def available(self) -> bool:
        return bool(self._say_bin or self._espeak_bin)

    def speak(self, text: str, interrupt: bool = True, rate: int = 185) -> None:
        """Speak `text` asynchronously without blocking the game loop."""
        if not self.enabled or not text or not self.available:
            return

        def _worker():
            with self._lock:
                if interrupt and self._proc is not None:
                    try:
                        if self._proc.poll() is None:
                            self._proc.terminate()
                    except Exception:
                        pass
                    self._proc = None

                try:
                    if self._say_bin:
                        self._proc = subprocess.Popen(
                            [self._say_bin, "-r", str(rate), text],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )
                    elif self._espeak_bin:
                        self._proc = subprocess.Popen(
                            [self._espeak_bin, "-s", str(rate), text],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )
                except Exception:
                    self._proc = None

        threading.Thread(target=_worker, daemon=True).start()

    def stop(self) -> None:
        """Immediately stop any active speech subprocess."""
        with self._lock:
            if self._proc is not None:
                try:
                    if self._proc.poll() is None:
                        self._proc.terminate()
                except Exception:
                    pass
                self._proc = None


# ── Visual Effect Data Structures ─────────────────────────────────────────────

@dataclass
class SparkParticle:
    x: float
    y: float
    vx: float
    vy: float
    color: Tuple[int, int, int]
    r: float
    life: float
    max_life: float


@dataclass
class ShockwaveRing:
    x: float
    y: float
    r: float
    max_r: float
    color: Tuple[int, int, int]
    life: float
    max_life: float


@dataclass
class FloatingPopup:
    x: float
    y: float
    text: str
    color: Tuple[int, int, int]
    life: float = 1.1
    max_life: float = 1.1
    vy: float = -55.0


@dataclass
class LaserBeam:
    start_x: float
    start_y: float
    end_x: float
    end_y: float
    color: Tuple[int, int, int]
    life: float = 0.45
    max_life: float = 0.45


# ── Rank Progression Table ────────────────────────────────────────────────────

RANKS = [
    (0,    "CYBER CADET",      NEON_CYAN),
    (300,  "STAR RANGER",      NEON_GREEN),
    (700,  "PLASMA KNIGHT",    NEON_YELLOW),
    (1200, "NOVA COMMANDER",   NEON_ORANGE),
    (2000, "QUANTUM LEGEND",   NEON_MAGENTA),
]

OP_MODES = ["MIXED", "MULTIPLY (×)", "ADD & SUB (±)", "DIVIDE (÷)"]


# ── Main Game Class ───────────────────────────────────────────────────────────

class MathChoiceGame:
    def __init__(self, screen, clock, debug=False, mode="accessible", audio=None, username=""):
        self.screen = screen
        self.clock = clock
        self.debug = debug
        self._debug = debug
        # Normalize mode ("accessible" / "astra" vs "standard" / "veera" / "keyboard")
        self.mode = "accessible" if mode in ("accessible", "astra") else mode
        self.audio = audio
        self.username = (username or "").strip()
        self.display_name = self.username if self.username else "Champion"

        if not pygame.font.get_init():
            pygame.font.init()

        # Background & visual managers
        self._nebula = NebulaBg()
        self._stars = StarField(n=90)
        self.hud = GestureHUD(scale=0.3)
        self.tts = MathTTS(enabled=True)

        # Score, streak, and progression
        self.score = 0
        self.questions_solved = 0
        self.streak = 0
        self.best_streak = 0
        self._last_celebrated_score = 0
        self._celebration: Optional[FireworksCelebration] = None
        self._op_mode_idx = 0  # 0=MIXED, 1=MUL, 2=ADD/SUB, 3=DIV

        # Tremor smoothing buffers for gyro movement (8-frame window for calmer response)
        self._gz_hist: deque = deque(maxlen=8)
        self._gy_hist: deque = deque(maxlen=8)
        self._gx_hist: deque = deque(maxlen=8)

        # Reticle trail & effects
        self._trail: deque = deque(maxlen=18)
        self._particles: List[SparkParticle] = []
        self._rings: List[ShockwaveRing] = []
        self._popups: List[FloatingPopup] = []
        self._laser: Optional[LaserBeam] = None
        self._screen_shake = 0.0
        self._anim_t = 0.0
        self._grid_scroll = 0.0

        # Dwell & gesture selection state (calmer, less hair-trigger timing)
        self.dwell_timer = 0.0
        self.dwell_side: Optional[str] = None
        self.dwell_required = 1.40 if self.mode == "accessible" else 1.55
        self._swipe_cooldown = 0.0
        self._move_override_timer = 0.0   # holds MOVE precedence so tilt doesn't fight back
        self._active_input_mode = "IDLE"  # "MOVE" | "TILT" | "IDLE"

        # Feedback / celebration state
        self.feedback_timer = 0.0
        self.feedback_type = ""        # "correct" | "wrong"
        self.feedback_headline = ""
        self.feedback_subtext = ""
        self.feedback_color = TEXT_WHITE
        self._pending_new_problem = False
        self._wrong_side_eliminated: Optional[str] = None  # dims wrong portal after a miss

        # Current problem fields
        self.problem_text = ""
        self.spoken_problem = ""
        self.correct_answer = 0
        self.left_ans = 0
        self.right_ans = 0
        self.is_boss_round = False
        self.boss_name = "MECHA-SENTINEL"

        # Initialize resolution-dependent layout
        self._init_layout(screen)
        self.selector_pos = float(self.W // 2)
        self.cursor_x = float(self.W // 2)
        self.cursor_y = float(self.H * 0.62)

        mx, my = pygame.mouse.get_pos()
        self._prev_mx = mx
        self._prev_my = my

        # Generate first problem (spoken when run() starts)
        self.generate_problem(speak_now=False)

    # ── Layout & Fullscreen Support ───────────────────────────────────────────

    @staticmethod
    def _make_font(size: int, bold: bool = True) -> pygame.font.Font:
        try:
            return pygame.font.SysFont("Arial", max(10, size), bold=bold)
        except Exception:
            return pygame.font.Font(None, max(12, int(size * 1.15)))

    def _init_layout(self, screen: pygame.Surface) -> None:
        self.screen = screen
        self._screen = screen
        self.W, self.H = screen.get_size()
        self._W, self._H = self.W, self.H
        self._is_fullscreen = not (self.W == 800 and self.H == 600)
        self.sc = min(self.W / 800.0, self.H / 600.0)
        sc = self.sc

        # Scalable typography
        self.font_hud = self._make_font(int(20 * sc), bold=True)
        self.font_small = self._make_font(int(15 * sc), bold=True)
        self.font_badge = self._make_font(int(17 * sc), bold=True)
        self.font_title = self._make_font(int(44 * sc), bold=True)
        self.font_problem = self._make_font(int(82 * sc), bold=True)
        self.font_answer = self._make_font(int(96 * sc), bold=True)
        self.font_feedback = self._make_font(int(36 * sc), bold=True)
        self.font_feedback_sub = self._make_font(int(23 * sc), bold=True)

        # Key anchor positions
        self.core_center = (self.W // 2, int(self.H * 0.25))
        self.left_portal = (int(self.W * 0.23), int(self.H * 0.57))
        self.right_portal = (int(self.W * 0.77), int(self.H * 0.57))
        self.portal_radius = int(96 * sc)
        self.turret_pos = (self.W // 2, int(self.H * 0.88))

        # Keep cursor inside new bounds
        if hasattr(self, "cursor_x"):
            self.cursor_x = max(40.0, min(float(self.W - 40), self.cursor_x))
            self.cursor_y = max(80.0, min(float(self.H - 60), self.cursor_y))
            self.selector_pos = self.cursor_x

    def _toggle_fullscreen(self) -> None:
        """Toggle between native fullscreen and 800x600 windowed mode."""
        self._is_fullscreen = not self._is_fullscreen
        if self._is_fullscreen:
            new_screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        else:
            new_screen = pygame.display.set_mode((800, 600))
        self._init_layout(new_screen)
        self.cursor_x = float(self.W // 2)
        self.cursor_y = float(self.H * 0.62)
        self.selector_pos = self.cursor_x

    # ── Problem Generation & TTS Announcements ────────────────────────────────

    def _get_rank_info(self) -> Tuple[str, Tuple[int, int, int]]:
        rank_name, rank_col = RANKS[0][1], RANKS[0][2]
        for threshold, name, col in RANKS:
            if self.score >= threshold:
                rank_name, rank_col = name, col
        return rank_name, rank_col

    def generate_problem(self, speak_now: bool = True) -> None:
        self._wrong_side_eliminated = None
        self.dwell_timer = 0.0
        self.dwell_side = None

        # Every 5th streak (when streak > 0) triggers a Boss Drone encounter!
        self.is_boss_round = (self.streak > 0 and self.streak % 5 == 0)
        if self.is_boss_round:
            self.boss_name = random.choice([
                "OMEGA MECHA-DRONE", "QUANTUM TITAN", "CYBER OVERLORD", "NOVA SENTINEL"
            ])

        # Determine math operation
        op_mode = OP_MODES[self._op_mode_idx]
        if op_mode == "MULTIPLY (×)":
            op = "mul"
        elif op_mode == "ADD & SUB (±)":
            op = random.choice(["add", "sub"])
        elif op_mode == "DIVIDE (÷)":
            op = "div"
        else:
            # MIXED: weighted toward multiplication & engaging teen mental math
            weights = ["mul", "mul", "add", "sub", "div"]
            if self.is_boss_round:
                weights.append("square")
            op = random.choice(weights)

        if op == "mul":
            max_f = 9 if self.mode == "accessible" and self.streak < 4 else 12
            a = random.randint(2, max_f)
            b = random.randint(2, max_f)
            self.correct_answer = a * b
            self.problem_text = f"{a} × {b}"
            self.spoken_problem = f"{a} times {b}"
            offsets = [-a, a, -b, b, -2, 2, -1, 1, 10, -10]
        elif op == "add":
            a = random.randint(12, 65)
            b = random.randint(11, 55)
            self.correct_answer = a + b
            self.problem_text = f"{a} + {b}"
            self.spoken_problem = f"{a} plus {b}"
            offsets = [-10, 10, -2, 2, -1, 1, -5, 5]
        elif op == "sub":
            a = random.randint(25, 95)
            b = random.randint(8, a - 5)
            self.correct_answer = a - b
            self.problem_text = f"{a} − {b}"
            self.spoken_problem = f"{a} minus {b}"
            offsets = [-10, 10, -2, 2, -1, 1, -4, 4]
        elif op == "div":
            b = random.randint(2, 10)
            q = random.randint(2, 11)
            a = b * q
            self.correct_answer = q
            self.problem_text = f"{a} ÷ {b}"
            self.spoken_problem = f"{a} divided by {b}"
            offsets = [-2, -1, 1, 2, 3, -3]
        else:  # square bonus
            a = random.randint(4, 12)
            self.correct_answer = a * a
            self.problem_text = f"{a}²"
            self.spoken_problem = f"{a} squared"
            offsets = [-a, a, -2, 2, 10, -10]

        # Pick a plausible distractor answer
        valid_offsets = [o for o in offsets if self.correct_answer + o > 0 and o != 0]
        wrong_answer = self.correct_answer + (random.choice(valid_offsets) if valid_offsets else 2)

        if random.random() > 0.5:
            self.left_ans = self.correct_answer
            self.right_ans = wrong_answer
        else:
            self.left_ans = wrong_answer
            self.right_ans = self.correct_answer

        if speak_now:
            self.speak_current_problem()

    def speak_current_problem(self) -> None:
        """Read the current math problem and the Left/Right options aloud via TTS."""
        prefix = f"Boss Round! " if self.is_boss_round else ""
        msg = (
            f"{prefix}What is {self.spoken_problem}? "
            f"Left is {self.left_ans}. Right is {self.right_ans}."
        )
        self.tts.speak(msg, interrupt=True)

    # ── Answer Evaluation & Personalized Appreciation / Motivation ────────────

    def check_answer(self, side: str) -> None:
        if self.feedback_timer > 0:
            return
        # If this wrong side was already tried on this question, ignore repeat trigger
        if self._wrong_side_eliminated == side:
            return

        target_pos = self.left_portal if side == "left" else self.right_portal
        chosen_val = self.left_ans if side == "left" else self.right_ans

        if chosen_val == self.correct_answer:
            self.handle_correct(side, target_pos)
        else:
            self.handle_wrong(side, target_pos)

    def handle_correct(self, side: str, target_pos: Tuple[int, int]) -> None:
        self.streak += 1
        self.best_streak = max(self.best_streak, self.streak)
        self.questions_solved += 1

        mult = min(4, 1 + (self.streak - 1) // 3)
        boss_bonus = 2 if self.is_boss_round else 1
        pts = 100 * mult * boss_bonus
        self.score += pts

        if self.audio:
            if self.is_boss_round or self.streak % 5 == 0:
                self.audio.play("fanfare")
            else:
                self.audio.play("powerup")

        # Fire plasma laser & spawn explosion particles at the chosen portal
        self._laser = LaserBeam(
            self.turret_pos[0], self.turret_pos[1] - int(20 * self.sc),
            target_pos[0], target_pos[1],
            NEON_GREEN, life=0.5, max_life=0.5
        )
        self._spawn_explosion(target_pos[0], target_pos[1], NEON_GREEN, count=55)
        if self.is_boss_round:
            self._spawn_explosion(self.core_center[0], self.core_center[1], NEON_MAGENTA, count=70)
        self._screen_shake = 8.0 if self.is_boss_round else 4.5

        self._popups.append(FloatingPopup(
            target_pos[0], target_pos[1] - int(50 * self.sc),
            f"+{pts} PTS!" + (" BOSS CRUSHED!" if self.is_boss_round else ""),
            NEON_YELLOW
        ))

        # Personalized appreciation messages with username
        name = self.display_name
        praise_templates = [
            (
                f"AWESOME JOB, {name.upper()}!",
                f"{self.problem_text} = {self.correct_answer}  •  Streak x{self.streak}!",
                f"Awesome job, {name}! {self.spoken_problem} is {self.correct_answer}!"
            ),
            (
                f"YOU CRUSHED IT, {name.upper()}!",
                f"Spot on! {self.problem_text} = {self.correct_answer}",
                f"You crushed it, {name}! {self.correct_answer} is spot on!"
            ),
            (
                f"BRILLIANT MOVE, {name.upper()}!",
                f"Direct hit! {self.problem_text} = {self.correct_answer}",
                f"Brilliant move, {name}! {self.spoken_problem} equals {self.correct_answer}!"
            ),
            (
                f"UNSTOPPABLE, {name.upper()}!",
                f"{self.streak} in a row! {self.problem_text} = {self.correct_answer}",
                f"Unstoppable, {name}! That's {self.streak} in a row! {self.correct_answer} is right!"
            ),
            (
                f"LEGENDARY SKILL, {name.upper()}!",
                f"Cyber Core Charged! {self.problem_text} = {self.correct_answer}",
                f"Legendary skill, {name}! {self.spoken_problem} is {self.correct_answer}!"
            ),
        ]
        headline, subtext, spoken = random.choice(praise_templates)

        self.feedback_type = "correct"
        self.feedback_headline = headline
        self.feedback_subtext = subtext
        self.feedback_color = NEON_GREEN
        self.feedback_timer = 2.1
        self._pending_new_problem = True
        self.dwell_timer = 0.0
        self.dwell_side = None

        # Speak personalized appreciation
        self.tts.speak(spoken, interrupt=True)

        # Check 1000-point milestone fireworks
        cur_ms = self.score // 1000
        last_ms = self._last_celebrated_score // 1000
        if cur_ms > last_ms and self.score > 0:
            self._celebration = FireworksCelebration(self.W, self.H, self.display_name, cur_ms * 1000)
            self._last_celebrated_score = self.score

    def handle_wrong(self, side: str, target_pos: Tuple[int, int]) -> None:
        self.streak = 0
        if self.audio:
            self.audio.play("brick_hit")

        # Visual shield deflection on the wrong portal (keeps the problem active!)
        self._wrong_side_eliminated = side
        self._laser = LaserBeam(
            self.turret_pos[0], self.turret_pos[1] - int(20 * self.sc),
            target_pos[0], target_pos[1],
            NEON_ORANGE, life=0.35, max_life=0.35
        )
        self._spawn_explosion(target_pos[0], target_pos[1], NEON_ORANGE, count=25)
        self._screen_shake = 3.0

        other_side = "right" if side == "left" else "left"
        name = self.display_name

        # Supportive, motivating messages with username (never discouraging!)
        encourage_templates = [
            (
                f"NICE TRY, {name.upper()}! YOU'VE GOT THIS!",
                f"Move toward the {other_side.upper()} portal ({self.correct_answer}) to crack {self.problem_text}!",
                f"Nice try, {name}! You've got this! Move {other_side} for {self.correct_answer}!"
            ),
            (
                f"GOOD EFFORT, {name.upper()}! KEEP GOING!",
                f"Almost there! Aim {other_side.upper()} to blast {self.correct_answer}!",
                f"Good effort, {name}! Almost there, move {other_side} for {self.correct_answer}!"
            ),
            (
                f"DON'T GIVE UP, {name.upper()}!",
                f"Every try builds your power! Swing {other_side.upper()} for {self.correct_answer}!",
                f"Don't give up, {name}! Swing {other_side} to hit {self.correct_answer}!"
            ),
            (
                f"SO CLOSE, {name.upper()}! TRY THE OTHER SIDE!",
                f"{self.problem_text} = {self.correct_answer}  •  Move {other_side.upper()} to lock it in!",
                f"So close, {name}! {self.spoken_problem} is {self.correct_answer}. Move {other_side}!"
            ),
        ]
        headline, subtext, spoken = random.choice(encourage_templates)

        self.feedback_type = "wrong"
        self.feedback_headline = headline
        self.feedback_subtext = subtext
        self.feedback_color = NEON_YELLOW
        self.feedback_timer = 1.6
        self._pending_new_problem = False
        self.dwell_timer = 0.0
        self.dwell_side = None

        # Speak supportive motivation with username
        self.tts.speak(spoken, interrupt=True)

    # ── Particle & Shockwave Spawners ─────────────────────────────────────────

    def _spawn_explosion(self, x: float, y: float, color: Tuple[int, int, int], count: int = 45) -> None:
        self._rings.append(ShockwaveRing(
            x=x, y=y, r=10 * self.sc, max_r=150 * self.sc,
            color=color, life=0.5, max_life=0.5
        ))
        for _ in range(count):
            ang = random.uniform(0, math.tau)
            spd = random.uniform(70, 360) * self.sc
            life = random.uniform(0.35, 0.85)
            # Mix primary color with white/gold sparks
            c = random.choice([color, color, TEXT_WHITE, NEON_YELLOW])
            self._particles.append(SparkParticle(
                x=x, y=y,
                vx=math.cos(ang) * spd,
                vy=math.sin(ang) * spd,
                color=c,
                r=random.uniform(2.5, 6.0) * self.sc,
                life=life,
                max_life=life,
            ))

    # ── Movement Gesture & Input Update ───────────────────────────────────────

    def _update_controls(self, gs, dt: float) -> None:
        """
        Arbitrates cleanly between MOVE gestures and TILT with calm responsiveness:
          1. MOVE PRECEDENCE: If the user makes an active hand/arm movement
             (horizontal gyro speed >= MOVE_THRESH), MOVE takes 100% precedence
             and wrist tilt is completely ignored (including a short holdover
             window so a tilted wrist never pulls the cursor the wrong way).
          2. TILT PRECEDENCE WHEN RESTING: Only when the hand is resting steady
             (low gyro movement) and tilting does wrist tilt smoothly steer the
             reticle.
          3. Calm Dwell Confirmation: Moving or tilting into an answer portal
             charges the visual lock-in ring (`dwell_required` ~1.4s) so the
             player never triggers accidental answers from brief twitches.
        """
        if self._swipe_cooldown > 0:
            self._swipe_cooldown = max(0.0, self._swipe_cooldown - dt)
        if self._move_override_timer > 0:
            self._move_override_timer = max(0.0, self._move_override_timer - dt)

        # 1. Check mouse movement
        mx, my = pygame.mouse.get_pos()
        mouse_moved = math.hypot(mx - self._prev_mx, my - self._prev_my) >= 3.0
        self._prev_mx, self._prev_my = mx, my

        if mouse_moved:
            self.cursor_x = float(mx)
            self.cursor_y = float(my)
            self._active_input_mode = "MOUSE"

        # 2. Keyboard continuous nudge
        keys = pygame.key.get_pressed()
        kb_vx = 0.0
        if keys[pygame.K_LEFT] or keys[pygame.K_a]:
            kb_vx -= 520.0 * self.sc
        if keys[pygame.K_RIGHT] or keys[pygame.K_d]:
            kb_vx += 520.0 * self.sc
        if kb_vx != 0.0:
            self.cursor_x += kb_vx * dt
            self.cursor_y += (self.left_portal[1] - self.cursor_y) * min(1.0, dt * 8.0)
            self._active_input_mode = "KEYS"

        # 3. Sensor Gesture & Movement Processing (MOVE vs TILT Precedence)
        if gs is not None:
            raw_gz = getattr(gs, "abs_gz", 0.0)
            raw_gy = getattr(gs, "abs_gy", 0.0)
            raw_gx = getattr(gs, "abs_gx", 0.0)

            # Smooth gyro readings over 8 frames to prevent twitchy jumps
            self._gz_hist.append(raw_gz)
            self._gy_hist.append(raw_gy)
            self._gx_hist.append(raw_gx)
            gz = sum(self._gz_hist) / len(self._gz_hist)
            gy = sum(self._gy_hist) / len(self._gy_hist)
            gx = sum(self._gx_hist) / len(self._gx_hist)

            # Horizontal movement signal:
            # In MetaMotion convention, -gz is horizontal arm/wrist movement
            # (moving left -> -gz < 0; moving right -> -gz > 0).
            move_horiz = -gz
            move_vert = -gy
            gyro_activity = math.hypot(gz, gy)

            # Thresholds for MOVE vs resting TILT arbitration
            move_precedence_thresh = 30.0 if self.mode == "accessible" else 38.0
            big_move_thresh = 135.0 if self.mode == "accessible" else 165.0
            rest_gyro_max = 20.0 if self.mode == "accessible" else 24.0
            tilt_deadzone = 0.14 if self.mode == "accessible" else 0.18

            vx = 0.0
            vy = 0.0

            # ── CASE A: User is making a bigger / active MOVE gesture ────────
            # Move takes 100% precedence over tilt! Even if the wrist is tilted
            # right while moving left, tilt is completely ignored.
            if abs(move_horiz) >= move_precedence_thresh:
                self._move_override_timer = 0.55  # lock out tilt for 0.55s after moving
                self._active_input_mode = "MOVE"

                gyro_scale_x = (4.2 if self.mode == "accessible" else 3.5) * self.sc
                gyro_scale_y = (3.0 if self.mode == "accessible" else 2.5) * self.sc
                vx = move_horiz * gyro_scale_x
                vy = (0.0 if abs(move_vert) < 20.0 else move_vert) * gyro_scale_y

                # If the user makes a deliberate, bigger directional swing toward
                # an answer, smoothly carry the reticle into that portal!
                if abs(move_horiz) >= big_move_thresh and self._swipe_cooldown <= 0:
                    move_side = "left" if move_horiz < 0 else "right"
                    if self._wrong_side_eliminated != move_side:
                        target = self.left_portal if move_side == "left" else self.right_portal
                        # Glide strongly toward target portal
                        self.cursor_x += (target[0] - self.cursor_x) * min(1.0, dt * 14.0)
                        self.cursor_y += (target[1] - self.cursor_y) * min(1.0, dt * 14.0)
                        # If it's a very strong, unmistakable swing (>= 195 deg/s),
                        # give a helpful boost to the dwell lock-in timer
                        if abs(move_horiz) >= 195.0:
                            self.dwell_side = move_side
                            self.dwell_timer = max(self.dwell_timer, self.dwell_required * 0.65)
                            self._swipe_cooldown = 0.45

            # ── CASE B: Holdover window right after an active MOVE ───────────
            # Prevents a tilted wrist from pulling the reticle back the wrong way
            # as the user's hand slows down at the end of a move.
            elif self._move_override_timer > 0:
                self._active_input_mode = "MOVE"
                if abs(move_horiz) >= 14.0:
                    gyro_scale_x = (3.6 if self.mode == "accessible" else 3.0) * self.sc
                    vx = move_horiz * gyro_scale_x

            # ── CASE C: Hand is resting still in space -> TILT takes precedence
            elif gyro_activity <= rest_gyro_max and abs(gs.paddle_velocity) >= tilt_deadzone:
                self._active_input_mode = "TILT"
                tilt_speed = (340.0 if self.mode == "accessible" else 300.0) * self.sc
                vx = gs.paddle_velocity * tilt_speed
                vy = getattr(gs, "tilt_y", 0.0) * (160.0 * self.sc)
            else:
                self._active_input_mode = "IDLE"

            self.cursor_x += vx * dt
            self.cursor_y += vy * dt

            # Gently align Y toward the portal plane
            portal_y = float(self.left_portal[1])
            self.cursor_y += (portal_y - self.cursor_y) * min(1.0, dt * 3.0)

        # Clamp cursor bounds
        margin_x = int(45 * self.sc)
        margin_y = int(75 * self.sc)
        self.cursor_x = max(float(margin_x), min(float(self.W - margin_x), self.cursor_x))
        self.cursor_y = max(float(margin_y), min(float(self.H - margin_y), self.cursor_y))
        self.selector_pos = self.cursor_x

        # 4. Determine active side & apply calm ASTRA Magnetic Intent Assist
        current_side: Optional[str] = None
        left_zone_x = self.W * (0.34 if self.mode == "accessible" else 0.31)
        right_zone_x = self.W * (0.66 if self.mode == "accessible" else 0.69)

        dist_left = math.hypot(self.cursor_x - self.left_portal[0], self.cursor_y - self.left_portal[1])
        dist_right = math.hypot(self.cursor_x - self.right_portal[0], self.cursor_y - self.right_portal[1])
        hit_r = self.portal_radius * (1.15 if self.mode == "accessible" else 1.05)

        if (self.cursor_x < left_zone_x or dist_left < hit_r) and self._wrong_side_eliminated != "left":
            current_side = "left"
            if self.mode == "accessible" and not mouse_moved and self._active_input_mode == "IDLE":
                # Soft stabilization toward left portal center once inside the zone
                self.cursor_x += (self.left_portal[0] - self.cursor_x) * min(1.0, dt * 2.4)
                self.cursor_y += (self.left_portal[1] - self.cursor_y) * min(1.0, dt * 2.4)
        elif (self.cursor_x > right_zone_x or dist_right < hit_r) and self._wrong_side_eliminated != "right":
            current_side = "right"
            if self.mode == "accessible" and not mouse_moved and self._active_input_mode == "IDLE":
                # Soft stabilization toward right portal center once inside the zone
                self.cursor_x += (self.right_portal[0] - self.cursor_x) * min(1.0, dt * 2.4)
                self.cursor_y += (self.right_portal[1] - self.cursor_y) * min(1.0, dt * 2.4)
        else:
            # Gentle centering drift when in the middle neutral zone and idle
            if not mouse_moved and kb_vx == 0.0 and self._active_input_mode == "IDLE":
                self.cursor_x += (self.W * 0.5 - self.cursor_x) * min(1.0, dt * 1.2)

        self.selector_pos = self.cursor_x
        self._trail.append((self.cursor_x, self.cursor_y))

        # 5. Dwell Lock-in
        if current_side:
            if current_side == self.dwell_side:
                self.dwell_timer += dt
                if self.dwell_timer >= self.dwell_required:
                    self.check_answer(current_side)
            else:
                self.dwell_side = current_side
                self.dwell_timer = dt
        else:
            self.dwell_side = None
            self.dwell_timer = max(0.0, self.dwell_timer - dt * 3.0)

    # ── Main Game Loop ────────────────────────────────────────────────────────

    def run(self, interpreter) -> str:
        if interpreter and getattr(interpreter, "config", None) is not None:
            if self.mode == "accessible":
                interpreter.config = CONFIG_ACCESSIBLE_FLICK_STEER
            else:
                interpreter.config = CONFIG_STANDARD

        if self.audio:
            self.audio.start_background()

        # Speak the initial math problem aloud
        self.speak_current_problem()

        dt = 0.016
        while True:
            # Check if display surface size changed externally
            cur_surf = pygame.display.get_surface()
            if cur_surf is not None and cur_surf.get_size() != (self.W, self.H):
                self._init_layout(cur_surf)

            # Handle celebration overlay if active
            if self._celebration is not None:
                if not self._celebration.update(dt):
                    self._celebration = None

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.tts.stop()
                    if self.audio:
                        self.audio.stop_background()
                    return "quit"
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        self.tts.stop()
                        if self.audio:
                            self.audio.stop_background()
                        if self.score > 0:
                            GameExitAppreciationScreen(
                                self.screen, self.clock, self.display_name, self.score
                            ).run(interpreter)
                        return "home"
                    elif event.key == pygame.K_f:
                        self._toggle_fullscreen()
                    elif event.key == pygame.K_d:
                        self.debug = not self.debug
                        self._debug = self.debug
                    elif event.key == pygame.K_s:
                        # Repeat spoken problem aloud
                        self.speak_current_problem()
                    elif event.key == pygame.K_m:
                        # Toggle TTS voice on/off
                        self.tts.enabled = not self.tts.enabled
                        if self.tts.enabled:
                            self.speak_current_problem()
                        else:
                            self.tts.stop()
                    elif event.key == pygame.K_o:
                        # Cycle math operation mode (Mixed / Multiply / Add-Sub / Divide)
                        self._op_mode_idx = (self._op_mode_idx + 1) % len(OP_MODES)
                        self.generate_problem(speak_now=True)
                    elif event.key in (pygame.K_LEFT, pygame.K_a) and self.feedback_timer <= 0:
                        if self._wrong_side_eliminated != "left":
                            self.cursor_x = float(self.left_portal[0])
                            self.cursor_y = float(self.left_portal[1])
                            self.selector_pos = self.cursor_x
                    elif event.key in (pygame.K_RIGHT, pygame.K_d) and self.feedback_timer <= 0:
                        if self._wrong_side_eliminated != "right":
                            self.cursor_x = float(self.right_portal[0])
                            self.cursor_y = float(self.right_portal[1])
                            self.selector_pos = self.cursor_x
                    elif event.key == pygame.K_1 and self.feedback_timer <= 0:
                        self.cursor_x, self.cursor_y = float(self.left_portal[0]), float(self.left_portal[1])
                        self.check_answer("left")
                    elif event.key == pygame.K_2 and self.feedback_timer <= 0:
                        self.cursor_x, self.cursor_y = float(self.right_portal[0]), float(self.right_portal[1])
                        self.check_answer("right")
                    elif event.key in (pygame.K_RETURN, pygame.K_SPACE) and self.feedback_timer <= 0:
                        if self.dwell_side:
                            self.check_answer(self.dwell_side)
                        else:
                            self.speak_current_problem()
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    mx, my = event.pos
                    if self.feedback_timer <= 0:
                        if math.hypot(mx - self.left_portal[0], my - self.left_portal[1]) <= self.portal_radius * 1.25:
                            self.cursor_x, self.cursor_y = float(self.left_portal[0]), float(self.left_portal[1])
                            self.check_answer("left")
                        elif math.hypot(mx - self.right_portal[0], my - self.right_portal[1]) <= self.portal_radius * 1.25:
                            self.cursor_x, self.cursor_y = float(self.right_portal[0]), float(self.right_portal[1])
                            self.check_answer("right")

            gs = interpreter.get_state() if interpreter else None

            # ── UPDATE ────────────────────────────────────────────────────────
            self._anim_t += dt
            self._grid_scroll = (self._grid_scroll + dt * 48.0) % 40.0
            self._screen_shake = max(0.0, self._screen_shake - dt * 18.0)
            self._nebula.update(dt)
            self._stars.update(dt)

            if self.audio:
                self.audio.update()

            # Update visual effects
            if self._laser is not None:
                self._laser.life -= dt
                if self._laser.life <= 0:
                    self._laser = None

            for p in self._particles:
                p.x += p.vx * dt
                p.y += p.vy * dt
                p.vy += 180.0 * self.sc * dt
                p.life -= dt
            self._particles = [p for p in self._particles if p.life > 0]

            for r in self._rings:
                r.life -= dt
                prog = 1.0 - max(0.0, r.life / r.max_life)
                r.r = (15.0 * self.sc) + (r.max_r - 15.0 * self.sc) * prog
            self._rings = [r for r in self._rings if r.life > 0]

            for pop in self._popups:
                pop.y += pop.vy * dt
                pop.life -= dt
            self._popups = [pop for pop in self._popups if pop.life > 0]

            # Update feedback timer & transition to next problem once praise finishes
            if self.feedback_timer > 0:
                self.feedback_timer -= dt
                self.cursor_x += (self.W * 0.5 - self.cursor_x) * min(1.0, dt * 6.0)
                self.cursor_y += (self.H * 0.62 - self.cursor_y) * min(1.0, dt * 6.0)
                self.selector_pos = self.cursor_x
                self.dwell_timer = 0.0
                if self.feedback_timer <= 0 and self._pending_new_problem:
                    self._pending_new_problem = False
                    self.generate_problem(speak_now=True)
            else:
                if self._celebration is None:
                    self._update_controls(gs, dt)

            # ── RENDER ────────────────────────────────────────────────────────
            self._draw(gs)
            pygame.display.flip()
            dt = self.clock.tick(60) / 1000.0

    # ── Rendering Helpers ─────────────────────────────────────────────────────

    def _draw(self, gs) -> None:
        sc = self.sc
        ox = int(random.uniform(-self._screen_shake, self._screen_shake)) if self._screen_shake > 0 else 0
        oy = int(random.uniform(-self._screen_shake, self._screen_shake)) if self._screen_shake > 0 else 0

        # 1. Deep Space + Nebula + 3D Perspective Cyber Grid
        self._nebula.draw(self.screen)
        self._stars.draw(self.screen)
        self._draw_cyber_grid(ox, oy)

        # 2. Central divider energy beam (subtle)
        mid_x = self.W // 2 + ox
        pygame.draw.line(
            self.screen, (35, 55, 90),
            (mid_x, int(self.H * 0.40)), (mid_x, int(self.H * 0.80)), max(1, int(2 * sc))
        )

        # 3. Draw Boss Mecha-Drone (if Boss Round) & Holographic Problem Reactor Core
        if self.is_boss_round:
            self._draw_boss_drone(self.core_center[0] + ox, int(self.H * 0.12) + oy)
        self._draw_problem_core(self.core_center[0] + ox, self.core_center[1] + oy)

        # 4. Draw Left & Right Hexagonal Answer Portals
        self._draw_answer_portal(
            "left", self.left_portal[0] + ox, self.left_portal[1] + oy,
            self.left_ans, NEON_CYAN
        )
        self._draw_answer_portal(
            "right", self.right_portal[0] + ox, self.right_portal[1] + oy,
            self.right_ans, NEON_MAGENTA
        )

        # 5. Draw Aiming Line, Plasma Laser Beam, Reticle Trail, & Cyber Turret
        self._draw_turret_and_reticle(ox, oy)

        # 6. Draw Shockwave Rings, Explosion Particles, & Floating Popups
        self._draw_effects(ox, oy)

        # 7. Draw Personalized Feedback Banner (Success / Motivation with Username)
        if self.feedback_timer > 0:
            self._draw_feedback_banner()

        # 8. Draw Top Arcade HUD Bar (Score, Rank, Streak, Voice/Fullscreen Controls)
        self._draw_top_hud()

        # 9. Milestone Fireworks Overlay
        if self._celebration is not None:
            self._celebration.draw(self.screen, self.font_title, self.font_feedback_sub)

        # 10. 3D Hand Gesture Avatar HUD
        if gs is not None:
            hud_margin = int(105 * sc)
            self.hud.draw(self.screen, gs, self.W - hud_margin, self.H - hud_margin)

        # 11. Debug overlay (D key)
        if self.debug and gs is not None:
            dbg_txt = (
                f"Input: {self._active_input_mode}  "
                f"Cursor: ({int(self.cursor_x)}, {int(self.cursor_y)})  "
                f"TiltVel: {gs.paddle_velocity:+.2f}  "
                f"MoveHoriz(-GyroZ): {-gs.abs_gz:+.1f}"
            )
            ds = self.font_small.render(dbg_txt, True, NEON_GREEN)
            self.screen.blit(ds, (int(16 * sc), self.H - int(28 * sc)))

    def _draw_cyber_grid(self, ox: int, oy: int) -> None:
        """Draw an animated 3D perspective neon synthwave horizon grid at the bottom."""
        horizon_y = int(self.H * 0.74) + oy
        bottom_y = self.H
        grid_col = (28, 65, 115)
        bright_col = (0, 160, 220)

        # Horizon glow line
        pygame.draw.line(self.screen, bright_col, (0, horizon_y), (self.W, horizon_y), 2)

        # Perspective radial lines fanning out from vanishing point
        vx = self.W // 2 + ox
        for i in range(-8, 9):
            bx = vx + int(i * 115 * self.sc)
            pygame.draw.line(self.screen, grid_col, (vx, horizon_y), (bx, bottom_y), 1)

        # Scrolling horizontal depth lines
        t_norm = (self._grid_scroll / 40.0)
        for row in range(6):
            frac = ((row + t_norm) / 6.0) ** 1.8
            y = int(horizon_y + (bottom_y - horizon_y) * frac)
            pygame.draw.line(self.screen, grid_col, (0, y), (self.W, y), 1)

    def _draw_boss_drone(self, cx: int, cy: int) -> None:
        """Draw an animated cartoon Cyber-Mecha Boss above the math core on boss rounds."""
        sc = self.sc
        bob = int(math.sin(self._anim_t * 4.5) * 6 * sc)
        cy += bob

        # Energy wings
        wing_span = int(125 * sc)
        wing_h = int(28 * sc)
        left_wing = [
            (cx - int(40 * sc), cy),
            (cx - wing_span, cy - wing_h),
            (cx - int(95 * sc), cy + wing_h),
        ]
        right_wing = [
            (cx + int(40 * sc), cy),
            (cx + wing_span, cy - wing_h),
            (cx + int(95 * sc), cy + wing_h),
        ]
        pygame.draw.polygon(self.screen, NEON_MAGENTA, left_wing)
        pygame.draw.polygon(self.screen, NEON_MAGENTA, right_wing)
        pygame.draw.polygon(self.screen, TEXT_WHITE, left_wing, 2)
        pygame.draw.polygon(self.screen, TEXT_WHITE, right_wing, 2)

        # Central Mecha Head chassis
        head_r = int(34 * sc)
        pygame.draw.circle(self.screen, (45, 25, 70), (cx, cy), head_r)
        pygame.draw.circle(self.screen, NEON_MAGENTA, (cx, cy), head_r, max(2, int(3 * sc)))

        # Glowing Cyber Visor Eyes
        eye_off = int(13 * sc)
        pygame.draw.polygon(self.screen, NEON_YELLOW, [
            (cx - eye_off - int(8 * sc), cy - int(6 * sc)),
            (cx - int(4 * sc), cy - int(2 * sc)),
            (cx - eye_off - int(6 * sc), cy + int(4 * sc)),
        ])
        pygame.draw.polygon(self.screen, NEON_YELLOW, [
            (cx + eye_off + int(8 * sc), cy - int(6 * sc)),
            (cx + int(4 * sc), cy - int(2 * sc)),
            (cx + eye_off + int(6 * sc), cy + int(4 * sc)),
        ])

        # Boss badge label
        boss_lbl = self.font_small.render(f"★ BOSS CHALLENGE: {self.boss_name} (2x SCORE) ★", True, NEON_YELLOW)
        self.screen.blit(boss_lbl, boss_lbl.get_rect(center=(cx, cy - int(46 * sc))))

    def _draw_problem_core(self, cx: int, cy: int) -> None:
        """Render the math problem inside a glowing sci-fi holographic reactor core."""
        sc = self.sc
        box_w = int(340 * sc)
        box_h = int(125 * sc)
        rect = pygame.Rect(cx - box_w // 2, cy - box_h // 2, box_w, box_h)

        accent = NEON_MAGENTA if self.is_boss_round else NEON_CYAN

        # Soft outer glow
        glow = make_glow(int(110 * sc), accent, 75)
        self.screen.blit(
            glow,
            (cx - glow.get_width() // 2, cy - glow.get_height() // 2),
            special_flags=pygame.BLEND_RGBA_ADD,
        )

        # Dark glassmorphic core panel
        panel = pygame.Surface((box_w, box_h), pygame.SRCALPHA)
        pygame.draw.rect(panel, (16, 26, 52, 225), panel.get_rect(), border_radius=int(22 * sc))
        self.screen.blit(panel, rect.topleft)
        pygame.draw.rect(self.screen, accent, rect, max(2, int(3 * sc)), border_radius=int(22 * sc))

        # Corner tech brackets
        blen = int(22 * sc)
        bw = max(2, int(4 * sc))
        for bx, by, sx, sy in [
            (rect.left - 4, rect.top - 4, 1, 1),
            (rect.right + 4, rect.top - 4, -1, 1),
            (rect.left - 4, rect.bottom + 4, 1, -1),
            (rect.right + 4, rect.bottom + 4, -1, -1),
        ]:
            pygame.draw.line(self.screen, NEON_YELLOW, (bx, by), (bx + sx * blen, by), bw)
            pygame.draw.line(self.screen, NEON_YELLOW, (bx, by), (bx, by + sy * blen), bw)

        # Display equation (show solved equation during correct celebration!)
        display_eq = (
            f"{self.problem_text} = {self.correct_answer}"
            if (self.feedback_timer > 0 and self.feedback_type == "correct")
            else self.problem_text
        )
        font_use = self.font_title if len(display_eq) > 7 else self.font_problem
        eq_col = NEON_GREEN if (self.feedback_timer > 0 and self.feedback_type == "correct") else TEXT_WHITE

        shadow = font_use.render(display_eq, True, (0, 0, 0))
        surf = font_use.render(display_eq, True, eq_col)
        self.screen.blit(shadow, shadow.get_rect(center=(cx + 3, cy + 3)))
        self.screen.blit(surf, surf.get_rect(center=(cx, cy)))

    def _draw_answer_portal(
        self,
        side: str,
        cx: int,
        cy: int,
        answer_val: int,
        base_color: Tuple[int, int, int],
    ) -> None:
        """Render a rotating hexagonal neon energy portal for an answer option."""
        sc = self.sc
        r = self.portal_radius
        is_hovered = (self.dwell_side == side and self.feedback_timer <= 0)
        is_eliminated = (self._wrong_side_eliminated == side)
        is_correct_reveal = (
            self.feedback_timer > 0
            and self.feedback_type == "correct"
            and answer_val == self.correct_answer
        )

        if is_eliminated:
            color = (75, 80, 100)
        elif is_correct_reveal or is_hovered:
            color = NEON_GREEN
        else:
            color = base_color

        # Pulse scale when hovered
        pulse = 1.0 + (0.06 * math.sin(self._anim_t * 8.0) if is_hovered else 0.02 * math.sin(self._anim_t * 3.0))
        r_scaled = int(r * pulse)

        # Radial glow behind portal
        if not is_eliminated:
            glow_r = int(r_scaled * (1.45 if is_hovered else 1.2))
            glow = make_glow(glow_r, color, 115 if is_hovered else 65)
            self.screen.blit(
                glow,
                (cx - glow.get_width() // 2, cy - glow.get_height() // 2),
                special_flags=pygame.BLEND_RGBA_ADD,
            )

        # Outer & inner counter-rotating hexagons
        rot1 = self._anim_t * (1.2 if is_hovered else 0.45) * (1 if side == "left" else -1)
        rot2 = -rot1 * 0.7
        hex_outer = [
            (
                int(cx + r_scaled * math.cos(rot1 + i * math.pi / 3)),
                int(cy + r_scaled * math.sin(rot1 + i * math.pi / 3)),
            )
            for i in range(6)
        ]
        hex_inner = [
            (
                int(cx + (r_scaled * 0.84) * math.cos(rot2 + i * math.pi / 3)),
                int(cy + (r_scaled * 0.84) * math.sin(rot2 + i * math.pi / 3)),
            )
            for i in range(6)
        ]

        # Translucent portal core fill
        fill_surf = pygame.Surface((r_scaled * 2 + 8, r_scaled * 2 + 8), pygame.SRCALPHA)
        local_hex = [(px - (cx - r_scaled - 4), py - (cy - r_scaled - 4)) for px, py in hex_outer]
        pygame.draw.polygon(fill_surf, (*color, 48 if not is_eliminated else 20), local_hex)
        self.screen.blit(fill_surf, (cx - r_scaled - 4, cy - r_scaled - 4))

        pygame.draw.polygon(self.screen, color, hex_outer, max(2, int(4 * sc)))
        pygame.draw.polygon(self.screen, (*color[:2], min(255, color[2] + 40)), hex_inner, max(1, int(2 * sc)))

        # Orbiting energy nodes on hex vertices
        if not is_eliminated:
            for vx, vy in hex_outer[::2]:
                pygame.draw.circle(self.screen, TEXT_WHITE, (vx, vy), max(3, int(5 * sc)))
                pygame.draw.circle(self.screen, color, (vx, vy), max(5, int(8 * sc)), 1)

        # Dwell Charge Ring (fills up smoothly as player holds reticle inside portal)
        if is_hovered and self.dwell_timer > 0:
            prog = min(1.0, self.dwell_timer / self.dwell_required)
            arc_r = r_scaled + int(14 * sc)
            arc_rect = pygame.Rect(cx - arc_r, cy - arc_r, arc_r * 2, arc_r * 2)
            pygame.draw.arc(
                self.screen, NEON_GREEN, arc_rect,
                math.pi / 2, math.pi / 2 + prog * math.tau, max(4, int(8 * sc))
            )

        # Answer Number
        num_col = (120, 125, 145) if is_eliminated else TEXT_WHITE
        ans_shadow = self.font_answer.render(str(answer_val), True, (0, 0, 0))
        ans_surf = self.font_answer.render(str(answer_val), True, num_col)
        self.screen.blit(ans_shadow, ans_shadow.get_rect(center=(cx + 3, cy + 3)))
        self.screen.blit(ans_surf, ans_surf.get_rect(center=(cx, cy)))

        # Directional gesture hint label below portal
        dir_label = "« MOVE / SWIPE LEFT" if side == "left" else "MOVE / SWIPE RIGHT »"
        if is_eliminated:
            dir_label = "TRY OTHER SIDE"
        lbl_surf = self.font_badge.render(dir_label, True, color)
        self.screen.blit(lbl_surf, lbl_surf.get_rect(center=(cx, cy + r_scaled + int(26 * sc))))

    def _draw_turret_and_reticle(self, ox: int, oy: int) -> None:
        """Draw the player's bottom-center Cyber Plasma Cannon and the motion-controlled reticle."""
        sc = self.sc
        tx, ty = self.turret_pos[0] + ox, self.turret_pos[1] + oy
        rx, ry = int(self.cursor_x) + ox, int(self.cursor_y) + oy

        # 1. Motion trail behind reticle
        pts = list(self._trail)
        if len(pts) >= 2:
            for i in range(1, len(pts)):
                frac = i / len(pts)
                p0 = (int(pts[i - 1][0]) + ox, int(pts[i - 1][1]) + oy)
                p1 = (int(pts[i][0]) + ox, int(pts[i][1]) + oy)
                col = (int(0 * frac), int(220 * frac), int(255 * frac))
                pygame.draw.line(self.screen, col, p0, p1, max(1, int(8 * sc * frac)))

        # 2. Active Laser Beam (when firing at an answer portal)
        if self._laser is not None:
            l_frac = max(0.0, self._laser.life / self._laser.max_life)
            w_outer = max(2, int(22 * sc * l_frac))
            w_inner = max(1, int(8 * sc * l_frac))
            p_start = (int(self._laser.start_x) + ox, int(self._laser.start_y) + oy)
            p_end = (int(self._laser.end_x) + ox, int(self._laser.end_y) + oy)
            pygame.draw.line(self.screen, self._laser.color, p_start, p_end, w_outer)
            pygame.draw.line(self.screen, TEXT_WHITE, p_start, p_end, w_inner)

        # 3. Dotted targeting laser from turret to reticle
        dx, dy = rx - tx, ry - ty
        dist = math.hypot(dx, dy) or 1.0
        angle = math.atan2(dy, dx)
        if self.feedback_timer <= 0:
            steps = int(dist // max(12, int(18 * sc)))
            for s_i in range(2, steps):
                frac = s_i / max(1, steps)
                px = int(tx + dx * frac)
                py = int(ty + dy * frac)
                pygame.draw.circle(self.screen, (70, 165, 220), (px, py), max(1, int(2 * sc)))

        # 4. Cyber Turret Base & Rotating Cannon Barrel
        barrel_len = int(46 * sc)
        barrel_w = max(6, int(12 * sc))
        bx_end = int(tx + math.cos(angle) * barrel_len)
        by_end = int(ty + math.sin(angle) * barrel_len)
        pygame.draw.line(self.screen, NEON_CYAN, (tx, ty), (bx_end, by_end), barrel_w)
        pygame.draw.line(self.screen, TEXT_WHITE, (tx, ty), (bx_end, by_end), max(2, barrel_w // 3))

        # Turret dome
        base_r = int(28 * sc)
        pygame.draw.circle(self.screen, (25, 40, 75), (tx, ty), base_r)
        pygame.draw.circle(self.screen, NEON_CYAN, (tx, ty), base_r, max(2, int(3 * sc)))
        pygame.draw.circle(self.screen, NEON_YELLOW, (tx, ty), int(10 * sc))

        # 5. Glowing Energy Reticle at cursor position
        if self.feedback_timer <= 0:
            ret_col = NEON_GREEN if self.dwell_side else NEON_YELLOW
            ret_r = int(22 * sc)
            glow = make_glow(int(36 * sc), ret_col, 140)
            self.screen.blit(
                glow,
                (rx - glow.get_width() // 2, ry - glow.get_height() // 2),
                special_flags=pygame.BLEND_RGBA_ADD,
            )
            pygame.draw.circle(self.screen, ret_col, (rx, ry), ret_r, max(2, int(3 * sc)))
            pygame.draw.circle(self.screen, TEXT_WHITE, (rx, ry), max(4, int(6 * sc)))
            # Crosshair ticks
            ch = int(30 * sc)
            pygame.draw.line(self.screen, ret_col, (rx - ch, ry), (rx - int(12 * sc), ry), 2)
            pygame.draw.line(self.screen, ret_col, (rx + int(12 * sc), ry), (rx + ch, ry), 2)
            pygame.draw.line(self.screen, ret_col, (rx, ry - ch), (rx, ry - int(12 * sc)), 2)
            pygame.draw.line(self.screen, ret_col, (rx, ry + int(12 * sc)), (rx, ry + ch), 2)

    def _draw_effects(self, ox: int, oy: int) -> None:
        for r in self._rings:
            w = max(1, int(5 * self.sc * (r.life / r.max_life)))
            pygame.draw.circle(self.screen, r.color, (int(r.x) + ox, int(r.y) + oy), int(r.r), w)

        for p in self._particles:
            frac = max(0.0, p.life / p.max_life)
            rad = max(1, int(p.r * frac))
            pygame.draw.circle(self.screen, p.color, (int(p.x) + ox, int(p.y) + oy), rad)

        for pop in self._popups:
            s = self.font_badge.render(pop.text, True, pop.color)
            self.screen.blit(s, s.get_rect(center=(int(pop.x) + ox, int(pop.y) + oy)))

    def _draw_feedback_banner(self) -> None:
        """Render a high-contrast personalized appreciation / motivation banner."""
        sc = self.sc
        bw = int(680 * sc)
        bh = int(105 * sc)
        cx, cy = self.W // 2, int(self.H * 0.42)
        rect = pygame.Rect(cx - bw // 2, cy - bh // 2, bw, bh)

        panel = pygame.Surface((bw, bh), pygame.SRCALPHA)
        bg_rgba = (15, 45, 30, 235) if self.feedback_type == "correct" else (45, 35, 15, 235)
        pygame.draw.rect(panel, bg_rgba, panel.get_rect(), border_radius=int(18 * sc))
        self.screen.blit(panel, rect.topleft)
        pygame.draw.rect(self.screen, self.feedback_color, rect, max(2, int(3 * sc)), border_radius=int(18 * sc))

        h_surf = self.font_feedback.render(self.feedback_headline, True, self.feedback_color)
        s_surf = self.font_feedback_sub.render(self.feedback_subtext, True, TEXT_WHITE)
        self.screen.blit(h_surf, h_surf.get_rect(center=(cx, cy - int(18 * sc))))
        self.screen.blit(s_surf, s_surf.get_rect(center=(cx, cy + int(22 * sc))))

    def _draw_top_hud(self) -> None:
        sc = self.sc
        pad = int(16 * sc)

        # Left: Score & Player Name
        score_s = self.font_hud.render(f"SCORE: {self.score}", True, TEXT_WHITE)
        self.screen.blit(score_s, (pad, pad))

        rank_name, rank_col = self._get_rank_info()
        rank_s = self.font_small.render(f"PILOT: {self.display_name.upper()}  •  RANK: {rank_name}", True, rank_col)
        self.screen.blit(rank_s, (pad, pad + int(26 * sc)))

        # Center-Top: Streak & Operation Mode Badge
        if self.streak > 0:
            mult = min(4, 1 + (self.streak - 1) // 3)
            streak_txt = f"STREAK: {self.streak}  (x{mult} OVERDRIVE)"
            st_col = NEON_YELLOW if self.streak < 5 else NEON_MAGENTA
        else:
            streak_txt = f"MODE: {OP_MODES[self._op_mode_idx]} [O]"
            st_col = TEXT_DIM
        st_surf = self.font_badge.render(streak_txt, True, st_col)
        self.screen.blit(st_surf, st_surf.get_rect(center=(self.W // 2, pad + int(12 * sc))))

        # Right: Voice TTS & Fullscreen & Mode shortcuts
        tts_lbl = "VOICE: ON [M]  •  REPEAT [S]" if self.tts.enabled else "VOICE: MUTED [M]"
        tts_col = NEON_GREEN if self.tts.enabled else TEXT_DIM
        tts_surf = self.font_small.render(tts_lbl, True, tts_col)
        self.screen.blit(tts_surf, tts_surf.get_rect(right=self.W - pad, top=pad))

        ctrl_lbl = "FULLSCREEN [F]  •  OPS [O]  •  MENU [ESC]"
        ctrl_surf = self.font_small.render(ctrl_lbl, True, TEXT_DIM)
        self.screen.blit(ctrl_surf, ctrl_surf.get_rect(right=self.W - pad, top=pad + int(24 * sc)))


def run(screen, clock, debug, mode, audio, username, interpreter):
    game = MathChoiceGame(screen, clock, debug, mode, audio, username)
    return game.run(interpreter)
