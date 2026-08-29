"""
games/magic_wand/game.py — A fun, engaging calibration game.

Teaches the player the core gestures (left, right, up, down, flick) by
having them move a "magic wand" to collect sparkling orbs.
"""

import math
import random
import pygame
from shared.learn_test_support import draw_gesture_debug_overlay
from shared.gesture_hud import GestureHUD
from typing import List, Optional, Tuple

import pygame

# ── Constants ─────────────────────────────────────────────────────────────────
W, H = 800, 600
FPS = 60

# ── Colors ────────────────────────────────────────────────────────────────────
BG = (25, 15, 45)
TEXT_CLR = (255, 255, 255)
DIM_CLR = (180, 180, 200)
ORB_CLR = (180, 120, 255)
SPARKLE_CLR = (220, 200, 255)
WAND_CLR = (140, 90, 60)
WAND_TIP_CLR = (255, 255, 100)

POSITIVE_WORDS = ["Great!", "Nice!", "Awesome!", "Super!", "Wow!"]
# ── Game states ───────────────────────────────────────────────────────────────
STATES = ["LEFT", "RIGHT", "UP", "DOWN", "FLICK", "DONE"]

@dataclass
class Particle:
    x: float; y: float
    vx: float; vy: float
    life: float; max_life: float
    color: Tuple[int, int, int]
    r: int

@dataclass
class FloatingText:
    x: float; y: float
    text: str
    color: Tuple[int, int, int]
    life: float = 1.2
    vy: float = -40.0

class MagicWandGame:
    def __init__(self, screen, clock, debug=False, mode="standard", audio=None, username=""):
        self._screen = screen
        self._clock = clock
        self._debug = debug
        self._mode = mode
        self._audio = audio
        self._username = username
        self.hud = GestureHUD("/Users/jerold/.gemini/antigravity-ide/brain/3c53c120-8bf4-4a05-a904-340edfef9b68/metamotion_kid_hand_flat_1788027714986.jpg", scale=0.3)
        self._gesture_src = None

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
        self._state_idx = 0
        self._wand_x = self._W // 2
        self._wand_y = self._H // 2
        self._particles: List[Particle] = []
        self._floating_texts: List[FloatingText] = []
        self._target_pos: Optional[Tuple[int, int]] = None
        self._reaction_timer = 0.0
        self._set_state(0)

    def _set_state(self, idx):
        self._state_idx = idx
        state = STATES[self._state_idx]
        sc = self._sc
        margin = int(120 * sc)
        if state == "LEFT":
            self._target_pos = (margin, self._H // 2)
        elif state == "RIGHT":
            self._target_pos = (self._W - margin, self._H // 2)
        elif state == "UP":
            self._target_pos = (self._W // 2, margin)
        elif state == "DOWN":
            self._target_pos = (self._W // 2, self._H - margin)
        elif state == "FLICK":
            self._target_pos = (self._W // 2, self._H // 2)
        else: # DONE
            self._target_pos = None
            if self._audio:
                self._audio.play_complete_fanfare()

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
        return None

    def _toggle_fullscreen(self):
        self._is_fullscreen = not self._is_fullscreen
        new_screen = pygame.display.set_mode((0, 0) if self._is_fullscreen else (W, H), pygame.FULLSCREEN if self._is_fullscreen else 0)
        self._init_layout(new_screen)
        self._reset()

    def _update(self, dt):
        if self._reaction_timer > 0:
            self._reaction_timer = max(0.0, self._reaction_timer - dt)

        gs = self._gesture_src.get_state() if self._gesture_src else None
        if gs and gs.calibrated:
            # Map Euler angles directly to screen position for pointing
            max_angle = 30.0
            roll = max(-max_angle, min(max_angle, gs.euler_roll))
            pitch = max(-max_angle, min(max_angle, gs.euler_pitch))

            self._wand_x = self._W * (roll + max_angle) / (2 * max_angle)
            self._wand_y = self._H * (pitch + max_angle) / (2 * max_angle)

            state = STATES[self._state_idx]
            if state == "FLICK":
                if gs.launch:
                    self._spawn_particles(self._wand_x, self._wand_y, 50)
                    if self._audio:
                        self._audio.play_flick_cast()
                    self._spawn_floating_text(self._wand_x, self._wand_y)
                    self._reaction_timer = 0.3
                    self._set_state(self._state_idx + 1)
            elif self._target_pos:
                dist = math.hypot(self._wand_x - self._target_pos[0], self._wand_y - self._target_pos[1])
                if dist < int(40 * self._sc):
                    self._spawn_particles(self._target_pos[0], self._target_pos[1], 30)
                    if self._audio: self._audio.play_collect()
                    self._spawn_floating_text(self._target_pos[0], self._target_pos[1])
                    self._reaction_timer = 0.3
                    self._set_state(self._state_idx + 1)

        # Update particles
        for p in self._particles:
            p.x += p.vx * dt
            p.y += p.vy * dt
            p.life -= dt
        self._particles = [p for p in self._particles if p.life > 0]
        self._update_floating_texts(dt)

    def _spawn_particles(self, x, y, count):
        for _ in range(count):
            angle = random.uniform(0, 2 * math.pi)
            speed = random.uniform(50, 250) * self._sc
            life = random.uniform(0.4, 1.2)
            self._particles.append(Particle(
                x=x, y=y, vx=speed * math.cos(angle), vy=speed * math.sin(angle),
                life=life, max_life=life,
                color=random.choice([SPARKLE_CLR, (255, 255, 180), (200, 180, 255)]),
                r=int(random.uniform(2, 5) * self._sc)
            ))

    def _spawn_floating_text(self, x, y):
        text = random.choice(POSITIVE_WORDS)
        color = random.choice([(255, 220, 60), (100, 255, 150), (120, 200, 255)])
        self._floating_texts.append(FloatingText(x=x, y=y, text=text, color=color))

    def _update_floating_texts(self, dt):
        for ft in self._floating_texts:
            ft.y += ft.vy * dt
            ft.life -= dt
        self._floating_texts = [ft for ft in self._floating_texts if ft.life > 0]

    def _draw(self):
        self._screen.fill(BG)
        self._draw_wizard()
        self._draw_particles()
        if self._target_pos:
            self._draw_orb(self._target_pos[0], self._target_pos[1])
        self._draw_wand()
        self._draw_floating_texts()
        self._draw_instructions()

    def _draw_wizard(self):
        sc = self._sc
        cx, cy = self._W // 2, self._H // 2 + int(50 * sc)

        # Bounce logic
        bounce_off = 0
        hat_hop = 0
        if self._reaction_timer > 0:
            # Smooth sine wave bounce
            progress = self._reaction_timer / 0.3
            bounce_off = int(math.sin(progress * math.pi) * 15 * sc)
            hat_hop = int(math.sin(progress * math.pi) * 12 * sc)

        cy -= bounce_off

        robe_h, robe_w = int(120 * sc), int(80 * sc)
        pygame.draw.polygon(self._screen, (80, 60, 150), [(cx, cy - robe_h // 2), (cx - robe_w // 2, cy + robe_h // 2), (cx + robe_w // 2, cy + robe_h // 2)])
        hat_h, hat_w = int(60 * sc), int(50 * sc)
        hat_y = cy - robe_h // 2 - hat_hop
        pygame.draw.polygon(self._screen, (60, 40, 120), [(cx, hat_y - hat_h), (cx - hat_w // 2, hat_y), (cx + hat_w // 2, hat_y)])
        pygame.draw.ellipse(self._screen, (60, 40, 120), (cx - hat_w, hat_y - int(5*sc), hat_w * 2, int(10*sc)))

    def _draw_wand(self):
        sc = self._sc
        wand_len = int(80 * sc)
        tip_pos = (self._wand_x - wand_len, self._wand_y + wand_len)
        pygame.draw.line(self._screen, WAND_CLR, (self._wand_x, self._wand_y), tip_pos, int(8 * sc))
        pygame.draw.circle(self._screen, WAND_TIP_CLR, tip_pos, int(10 * sc))
        glow_r = int(15 * sc)
        glow_surf = pygame.Surface((glow_r * 2, glow_r * 2), pygame.SRCALPHA)
        pygame.draw.circle(glow_surf, (255, 255, 180, 80), (glow_r, glow_r), glow_r)
        self._screen.blit(glow_surf, (tip_pos[0] - glow_r, tip_pos[1] - glow_r))

    def _draw_orb(self, x, y):
        sc = self._sc
        r = int(30 * sc)
        phase = (pygame.time.get_ticks() / 400) % (2 * math.pi)
        
        # Calculate proximity to wand for dynamic glow
        dist = math.hypot(self._wand_x - x, self._wand_y - y)
        proximity = max(0.0, 1.0 - (dist / (400 * sc))) ** 2
        
        pulse_factor = (1 + math.sin(phase)) / 2
        
        glow_r = r + int((10 + proximity * 30) * sc * pulse_factor) + int(proximity * 20 * sc)
        glow_alpha = min(255, int(50 + 40 * pulse_factor + proximity * 120))
        
        glow_surf = pygame.Surface((glow_r * 2, glow_r * 2), pygame.SRCALPHA)
        pygame.draw.circle(glow_surf, (*ORB_CLR, glow_alpha), (glow_r, glow_r), glow_r)
        self._screen.blit(glow_surf, (x - glow_r, y - glow_r))
        pygame.draw.circle(self._screen, ORB_CLR, (x, y), r)
        pygame.draw.circle(self._screen, (220, 200, 255), (x - int(8*sc), y - int(8*sc)), int(8*sc))

    def _draw_particles(self):
        for p in self._particles:
            alpha = int(255 * (p.life / p.max_life))
            s = pygame.Surface((p.r * 2, p.r * 2), pygame.SRCALPHA)
            pygame.draw.circle(s, (*p.color, alpha), (p.r, p.r), p.r)
            self._screen.blit(s, (int(p.x) - p.r, int(p.y) - p.r))

    def _draw_floating_texts(self):
        for ft in self._floating_texts:
            alpha = max(0, min(255, int(255 * ft.life / 1.2)))
            s = self._font_md.render(ft.text, True, ft.color)
            s.set_alpha(alpha)
            self._screen.blit(s, s.get_rect(center=(int(ft.x), int(ft.y))))

    def _draw_instructions(self):
        sc = self._sc
        state = STATES[self._state_idx]
        text = "All done! You're a natural!" if state == "DONE" else "Move your wand to the magic orb!"
        subtext = "Press ESC to return." if state == "DONE" else f"Let's learn to move {state.lower()}."
        if state == "FLICK": text = "Now, FLICK your wrist UP to cast a spell!"

        title_surf = self._font_md.render(text, True, TEXT_CLR)
        self._screen.blit(title_surf, title_surf.get_rect(center=(self._W // 2, int(60 * sc))))
        if subtext:
            sub_surf = self._font_sm.render(subtext, True, DIM_CLR)
            self._screen.blit(sub_surf, sub_surf.get_rect(center=(self._W // 2, int(90 * sc))))
