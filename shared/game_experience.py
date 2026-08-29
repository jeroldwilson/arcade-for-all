"""
game_experience.py — Shared visual effects and gameplay experience helpers.

New in pygame-ce upgrade:
  NebulaBg      — animated drifting color-blob background
  GlowSurface   — cached radial gradient alpha surfaces for glows
  KatanaTrail   — tapered, fading blade trail for Fruit Ninja cursor
  JuiceSplatter — juice particle burst on fruit slice
  ComboFlash    — radial flash + combo text animation
  StarField     — parallax star layers for Bricks background
  Particle / VisualEffects — upgraded with size, shape, batching
"""

import math
import random
import time
import functools
from typing import List, Optional, Tuple

import pygame

# ── NebulaBg ──────────────────────────────────────────────────────────────────

class NebulaBg:
    """Simple geometric pattern background (replaces the bright nebula blobs)."""

    def __init__(self):
        self._t = 0.0
        self._surf: Optional[pygame.Surface] = None
        self._last_size: Tuple[int, int] = (0, 0)
        self._colors = [(10, 15, 30), (15, 25, 45), (20, 35, 60)] # Muted navy/slate

    def update(self, dt: float) -> None:
        self._t += dt

    def draw(self, screen: pygame.Surface) -> None:
        W, H = screen.get_size()
        # Redraw simple geometric background every frame with slight motion
        screen.fill(self._colors[0])
        
        # Slow moving geometric grid
        offset_x = (self._t * 15) % 80
        offset_y = (self._t * 10) % 80
        
        # Draw some subtle polygons
        poly1 = [(W * 0.1, H * 0.2 + offset_y), (W * 0.8, H * 0.1), (W * 0.9, H * 0.6 + offset_y), (W * 0.3, H * 0.8)]
        poly2 = [(W * 0.2 + offset_x, H * 0.5), (W * 0.9, H * 0.7), (W * 0.6, H * 0.9), (W * 0.1, H * 0.7 + offset_x)]
        pygame.draw.polygon(screen, self._colors[1], poly1)
        pygame.draw.polygon(screen, self._colors[2], poly2)


# ── GlowSurface ───────────────────────────────────────────────────────────────

@functools.lru_cache(maxsize=128)
def make_glow(radius: int, color: Tuple[int, int, int], max_alpha: int = 180) -> pygame.Surface:
    """Return a cached radial-gradient alpha surface (2r x 2r) for `color`."""
    size = radius * 2
    surf = pygame.Surface((size, size), pygame.SRCALPHA)
    for i in range(radius, 0, -1):
        frac  = i / radius
        alpha = int(max_alpha * (1 - frac) ** 1.5)
        pygame.draw.circle(surf, (*color, alpha), (radius, radius), i)
    return surf


# ── StarField ─────────────────────────────────────────────────────────────────

class StarField:
    """Parallax star layers — used by Bricks game background."""

    def __init__(self, n: int = 120):
        self._stars: List[dict] = []
        for _ in range(n):
            self._stars.append({
                "x": random.random(),
                "y": random.random(),
                "speed": random.uniform(0.005, 0.025),
                "brightness": random.randint(80, 220),
                "size": random.choice([1, 1, 1, 2]),
            })

    def update(self, dt: float) -> None:
        for s in self._stars:
            s["y"] += s["speed"] * dt
            if s["y"] > 1.0:
                s["y"] = 0.0
                s["x"] = random.random()

    def draw(self, screen: pygame.Surface) -> None:
        W, H = screen.get_size()
        for s in self._stars:
            x = int(s["x"] * W)
            y = int(s["y"] * H)
            b = s["brightness"]
            if s["size"] == 1:
                screen.set_at((x, y), (b, b, b))
            else:
                pygame.draw.circle(screen, (b, b, b), (x, y), 1)


# ── KatanaTrail ───────────────────────────────────────────────────────────────

class KatanaTrail:
    """Stores last N cursor positions and renders a tapered fading blade trail."""

    MAX_LEN = 16

    def __init__(self):
        self._points: List[Tuple[float, float]] = []

    def add(self, x: float, y: float) -> None:
        self._points.append((x, y))
        if len(self._points) > self.MAX_LEN:
            self._points.pop(0)

    def clear(self) -> None:
        self._points.clear()

    def draw(self, screen: pygame.Surface, base_width: int = 18) -> None:
        n = len(self._points)
        if n < 2:
            return
        for i in range(1, n):
            frac   = i / n                          # 0=oldest → 1=newest
            alpha  = int(220 * frac)
            width  = max(1, int(base_width * frac))
            p0     = self._points[i - 1]
            p1     = self._points[i]
            # Core blade line — bright white-blue
            trail_surf = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
            pygame.draw.line(trail_surf, (200, 230, 255, alpha), (int(p0[0]), int(p0[1])),
                             (int(p1[0]), int(p1[1])), width)
            # Inner bright core
            if width > 2:
                pygame.draw.line(trail_surf, (255, 255, 255, min(255, alpha + 40)),
                                 (int(p0[0]), int(p0[1])), (int(p1[0]), int(p1[1])), max(1, width // 3))
            screen.blit(trail_surf, (0, 0))

        # Tip spark at newest point
        if self._points:
            tip = self._points[-1]
            glow = make_glow(14, (180, 220, 255), 160)
            screen.blit(glow, (int(tip[0]) - 14, int(tip[1]) - 14),
                        special_flags=pygame.BLEND_RGBA_ADD)
            pygame.draw.circle(screen, (255, 255, 255), (int(tip[0]), int(tip[1])), 3)


# ── JuiceSplatter ─────────────────────────────────────────────────────────────

class JuiceParticle:
    __slots__ = ("x", "y", "vx", "vy", "color", "life", "size")

    def __init__(self, x: float, y: float, color: Tuple[int, int, int],
                 vx: float, vy: float, size: float):
        self.x, self.y   = x, y
        self.vx, self.vy = vx, vy
        self.color       = color
        self.life        = 1.0
        self.size        = size

    def update(self, dt: float) -> None:
        self.vy  += 420 * dt
        self.x   += self.vx * dt
        self.y   += self.vy * dt
        self.life -= dt * 1.4

    def draw(self, screen: pygame.Surface) -> None:
        if self.life <= 0:
            return
        # Avoid creating surfaces every frame to prevent garbage collection stutters
        # Instead of alpha fade, we just shrink the radius which looks fine for juice
        r = max(1, int(self.size * self.life))
        pygame.draw.circle(screen, self.color, (int(self.x), int(self.y)), r)


class JuiceSplatter:
    """Spawn juice particles on fruit slice."""

    def __init__(self):
        self._particles: List[JuiceParticle] = []

    def spawn(self, x: float, y: float, color: Tuple[int, int, int], n: int = 30) -> None:
        for _ in range(n):
            angle  = random.uniform(0, math.tau)
            speed  = random.uniform(60, 320)
            size   = random.uniform(3, 9)
            bright = tuple(max(0, min(255, c + random.randint(-30, 60))) for c in color)
            self._particles.append(JuiceParticle(
                x, y, bright,            # type: ignore[arg-type]
                math.cos(angle) * speed,
                math.sin(angle) * speed - random.uniform(50, 150),
                size,
            ))

    def update(self, dt: float) -> None:
        for p in self._particles:
            p.update(dt)
        self._particles = [p for p in self._particles if p.life > 0]

    def draw(self, screen: pygame.Surface) -> None:
        for p in self._particles:
            p.draw(screen)


# ── ComboFlash ────────────────────────────────────────────────────────────────

class ComboFlash:
    """Radial flash + 'COMBO x3!' text animation."""

    def __init__(self):
        self._active   = False
        self._timer    = 0.0
        self._duration = 0.5
        self._x        = 0.0
        self._y        = 0.0
        self._count    = 0
        self._font: Optional[pygame.font.Font] = None

    def _ensure_font(self) -> None:
        if self._font is None:
            self._font = pygame.font.SysFont("Arial", 42, bold=True)

    def trigger(self, x: float, y: float, count: int) -> None:
        self._active   = True
        self._timer    = self._duration
        self._x, self._y = x, y
        self._count    = count

    def update(self, dt: float) -> None:
        if self._active:
            self._timer = max(0.0, self._timer - dt)
            if self._timer <= 0:
                self._active = False

    def draw(self, screen: pygame.Surface) -> None:
        if not self._active:
            return
        self._ensure_font()
        frac   = self._timer / self._duration
        alpha  = int(frac * 220)
        radius = int((1 - frac) * 80 + 20)

        # Radial flash
        glow = make_glow(radius, (255, 240, 100), alpha)
        screen.blit(glow, (int(self._x) - radius, int(self._y) - radius),
                    special_flags=pygame.BLEND_RGBA_ADD)

        # Combo text
        scale  = 0.6 + frac * 0.7
        text   = f"COMBO x{self._count}!"
        surf   = self._font.render(text, True, (255, 230, 60))
        surf   = pygame.transform.smoothscale(
            surf, (int(surf.get_width() * scale), int(surf.get_height() * scale))
        )
        surf.set_alpha(alpha)
        screen.blit(surf, surf.get_rect(center=(int(self._x), int(self._y) - 50)))


# ── Particle / VisualEffects (upgraded) ───────────────────────────────────────

class Particle:
    __slots__ = ("x", "y", "vx", "vy", "color", "life", "max_life", "size")

    def __init__(self, x: float, y: float, color: Tuple[int, int, int],
                 size: float = 4.0):
        self.x, self.y   = x, y
        self.vx          = random.uniform(-200, 200)
        self.vy          = random.uniform(-400, 100)
        self.color       = color
        self.max_life    = random.uniform(0.5, 1.5)
        self.life        = self.max_life
        self.size        = size

    def update(self, dt: float) -> None:
        self.vy  += 400 * dt
        self.x   += self.vx * dt
        self.y   += self.vy * dt
        self.life -= dt

    def draw(self, screen: pygame.Surface) -> None:
        if self.life <= 0:
            return
        frac  = self.life / self.max_life
        r     = max(1, int(self.size * frac))
        # Draw directly to screen to avoid creating garbage surfaces
        pygame.draw.circle(screen, self.color, (int(self.x), int(self.y)), r)


class VisualEffects:
    def __init__(self, sensor=None):
        self.particles: List[Particle] = []
        self.sensor = sensor

    def trigger_point_gain(self, x: float, y: float) -> None:
        color = (random.randint(150, 255), random.randint(150, 255), 50)
        for _ in range(15):
            self.particles.append(Particle(x, y, color, size=random.uniform(2, 6)))

    def trigger_fireworks(self, x: float, y: float) -> None:
        if self.sensor:
            self.sensor.vibrate(0.5)
            self.sensor.set_ambient_light(on=True, color=random.choice([0, 1, 2]), blink=True)
        color = (random.randint(100, 255), random.randint(100, 255), random.randint(100, 255))
        for _ in range(60):
            self.particles.append(Particle(x, y, color, size=random.uniform(3, 8)))

    def trigger_brick_destroy(self, x: float, y: float,
                              color: Tuple[int, int, int], n: int = 14) -> None:
        for _ in range(n):
            bright = tuple(max(0, min(255, c + random.randint(-20, 60))) for c in color)
            self.particles.append(Particle(x, y, bright, size=random.uniform(3, 7)))  # type: ignore[arg-type]

    def trigger_resume(self) -> None:
        if self.sensor:
            self.sensor.vibrate(0.2)

    def trigger_pause(self) -> None:
        pass

    def update(self, dt: float) -> None:
        for p in self.particles:
            p.update(dt)
        self.particles = [p for p in self.particles if p.life > 0]

    def draw(self, screen: pygame.Surface) -> None:
        for p in self.particles:
            p.draw(screen)


# ── InactivityMonitor ─────────────────────────────────────────────────────────

class InactivityMonitor:
    def __init__(self, username: str, sensor=None, audio=None):
        self.username             = username or "Player"
        self.sensor               = sensor
        self.audio                = audio
        self.last_motion_time     = time.time()
        self.last_pulse_time      = 0.0
        self.last_encourage_time  = 0.0
        self.is_paused            = False
        self.message              = ""
        self.message_color        = (255, 255, 255)

        # Thresholds from central config (edit shared/gameplay_config.py)
        from shared.gameplay_config import INACTIVITY_CONFIG as _cfg
        self.inactivity_threshold = _cfg.wake_up_sec
        self.pause_threshold      = _cfg.auto_pause_sec
        self._pulse_interval      = _cfg.pulse_interval_sec

        self.woke_up              = False
        self._font: Optional[pygame.font.Font] = None
        self._small_font: Optional[pygame.font.Font] = None

    def _ensure_fonts(self) -> None:
        if self._font is None:
            self._font       = pygame.font.SysFont("Arial", 48, bold=True)
            self._small_font = pygame.font.SysFont("Arial", 32)

    def update(self, is_moving: bool, is_manually_paused: bool = False) -> Optional[str]:
        now = time.time()
        if is_manually_paused:
            self.last_motion_time = now
            self.message          = ""
            return None
        if is_moving:
            self.last_motion_time = now
            if self.is_paused:
                self.is_paused = False
                self.message   = ""
                if self.sensor:
                    self.sensor.set_ambient_light(on=False)
                return "RESUME"
            if self.woke_up:
                # Keep the wake up message on screen for at least 10 seconds
                if now - getattr(self, "wake_up_trigger_time", 0.0) >= 10.0:
                    self.woke_up = False
                    self.message = ""
                    if self.sensor:
                        self.sensor.set_ambient_light(on=False)
            return None
        inactive_dur = now - self.last_motion_time
        if inactive_dur > self.pause_threshold:
            if not self.is_paused:
                self.is_paused = True
                self.message   = "PAUSED — MAKE A MOVE TO RESUME"
                if self.sensor:
                    self.sensor.set_ambient_light(on=False)
                return "PAUSE"
        elif inactive_dur > self.inactivity_threshold and not self.is_paused:
            if not self.woke_up:
                self.woke_up = True
                self.wake_up_trigger_time = now
            
            # Play encourage audio with 50s cooldown
            if self.audio and (now - self.last_encourage_time > 50.0):
                self.last_encourage_time = now
                self.audio.play_encourage(self.username)

            if now - self.last_pulse_time > self._pulse_interval:
                self.last_pulse_time = now
                if self.sensor:
                    self.sensor.vibrate(0.3)
                    self.sensor.set_ambient_light(on=True, color=random.choice([0, 1, 2]), blink=True)
                messages = [
                    f"Come on {self.username}, you can do it!",
                    f"Keep going {self.username}!",
                    f"Wake up {self.username}, time to play!",
                    "Don't give up!",
                    "Make a move!",
                ]
                self.message       = random.choice(messages)
                self.message_color = (
                    random.randint(150, 255), random.randint(150, 255), random.randint(150, 255)
                )
        return None

    def draw(self, screen: pygame.Surface) -> None:
        if not self.message:
            return
        self._ensure_fonts()

        # 1. Load mango sprite on demand if we haven't tried yet
        if not hasattr(self, '_mango_sprite_loaded'):
            self._mango_sprite_loaded = True
            import os
            sprite_path = "assets/images/mango_character.png"
            if os.path.exists(sprite_path):
                try:
                    self.mango_sprite = pygame.image.load(sprite_path).convert_alpha()
                    # Scale to a standard large size for display
                    self.mango_sprite = pygame.transform.smoothscale(self.mango_sprite, (220, 220))
                except Exception as e:
                    print(f"Error loading mango sprite: {e}")
                    self.mango_sprite = None
            else:
                self.mango_sprite = None

        # 2. Render text message
        text_surf = self._font.render(self.message, True, self.message_color)
        text_rect = text_surf.get_rect()

        # 3. Handle animated mango
        now = time.time()
        if hasattr(self, 'mango_sprite') and self.mango_sprite is not None:
            # Waving angle oscillates between -12 and 12 degrees
            angle = 12.0 * math.sin(now * 6.0)
            # Breathing scale oscillates between 0.95 and 1.05
            scale_factor = 1.0 + 0.05 * math.sin(now * 3.0)

            # Perform scaling
            w, h = self.mango_sprite.get_size()
            scaled_sprite = pygame.transform.smoothscale(
                self.mango_sprite, (int(w * scale_factor), int(h * scale_factor))
            )
            # Perform rotation
            rotated_sprite = pygame.transform.rotate(scaled_sprite, angle)
            sprite_rect = rotated_sprite.get_rect()

            # Center layout
            cx, cy = screen.get_width() // 2, screen.get_height() // 2
            spacing = 20
            total_height = sprite_rect.height + spacing + text_rect.height

            # Positions
            start_y = cy - total_height // 2
            sprite_rect.centerx = cx
            sprite_rect.top = start_y

            text_rect.centerx = cx
            text_rect.top = sprite_rect.bottom + spacing

            screen.blit(rotated_sprite, sprite_rect)
            screen.blit(text_surf, text_rect)
        else:
            # Fallback to text-only layout if no mango sprite
            rect = text_surf.get_rect(center=(screen.get_width() // 2, screen.get_height() // 2))
            screen.blit(text_surf, rect)


# ── GameGoal / GameGoalsPrompt ────────────────────────────────────────────────

class GameGoal:
    def __init__(self, target_score: int = 0, target_time_sec: int = 0):
        self.target_score    = target_score
        self.target_time_sec = target_time_sec
        self.indefinite      = (target_score == 0 and target_time_sec == 0)
        self.start_time      = 0.0

    def start(self) -> None:
        self.start_time = time.time()

    def check_met(self, current_score: int) -> bool:
        if self.indefinite:
            return False
        if self.target_score > 0 and current_score >= self.target_score:
            return True
        if self.target_time_sec > 0 and (time.time() - self.start_time) >= self.target_time_sec:
            return True
        return False


class GameGoalsPrompt:
    def __init__(self, screen: pygame.Surface, clock: pygame.time.Clock, mode: str = "standard"):
        self.screen       = screen
        self.clock        = clock
        self.mode         = mode
        self._W, self._H  = screen.get_size()
        sc = min(self._W / 800, self._H / 600)
        self._sc = sc

        self.options = [
            ("INDEFINITE", GameGoal(target_score=0, target_time_sec=0), [
                "Play indefinitely.", "No score or time limits.", "Great for training!"
            ], (110, 200, 255)),
            ("SCORE TARGET", GameGoal(target_score=1000, target_time_sec=0), [
                "Goal: 1000 Points.", "Classic arcade challenge.", "Test your endurance!"
            ], (255, 140, 60)),
            ("TIME TARGET", GameGoal(target_score=0, target_time_sec=120), [
                "Goal: 2 Minutes.", "Score as much as possible!", "Race against the clock."
            ], (100, 240, 120))
        ]

        # "astra mode by default in indefinite mode"
        # If mode is accessible (Astra), start with indefinite (index 0) selected
        self.selected_idx = 0

        self._font_title = pygame.font.SysFont("Arial", max(20, int(42 * sc)), bold=True)
        self._font_sub   = pygame.font.SysFont("Arial", max(8, int(14 * sc)))
        self._font_card  = pygame.font.SysFont("Arial", max(14, int(22 * sc)), bold=True)
        self._font_desc  = pygame.font.SysFont("Arial", max(7, int(12 * sc)))

        self._nebula = NebulaBg()
        self._card_rects = []
        self._init_layout()

    def _init_layout(self) -> None:
        sc = self._sc
        card_w = int(200 * sc)
        card_h = int(260 * sc)
        card_y = int(160 * sc)
        gap    = int(30 * sc)

        total_w = 3 * card_w + 2 * gap
        margin  = (self._W - total_w) // 2

        self._card_rects = []
        for i in range(3):
            x = margin + i * (card_w + gap)
            self._card_rects.append(pygame.Rect(x, card_y, card_w, card_h))

    def run(self, gesture_src=None) -> Optional[GameGoal]:
        pygame.mouse.set_visible(True)
        tilt_dir = 0
        nav_cd = 0.0

        while True:
            dt = self.clock.tick(60) / 1000.0
            nav_cd = max(0.0, nav_cd - dt)

            # Keyboard & Mouse events
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return None
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_LEFT:
                        self.selected_idx = (self.selected_idx - 1) % 3
                    elif event.key == pygame.K_RIGHT:
                        self.selected_idx = (self.selected_idx + 1) % 3
                    elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
                        return self.options[self.selected_idx][1]
                    elif event.key == pygame.K_ESCAPE:
                        return None
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    for i, rect in enumerate(self._card_rects):
                        if rect.collidepoint(pygame.mouse.get_pos()):
                            return self.options[i][1]

            # Mouse hover updates selection
            mx, my = pygame.mouse.get_pos()
            for i, rect in enumerate(self._card_rects):
                if rect.collidepoint(mx, my):
                    self.selected_idx = i

            # Gestures
            if gesture_src is not None:
                gs = gesture_src.get_state()
                if gs.calibrated:
                    if gs.launch:
                        return self.options[self.selected_idx][1]

                    direction = 0
                    if gs.paddle_velocity < -0.55:
                        direction = -1
                    elif gs.paddle_velocity > 0.55:
                        direction = 1

                    if direction != 0 and direction != tilt_dir and nav_cd <= 0:
                        self.selected_idx = (self.selected_idx + direction) % 3
                        nav_cd = 1.2
                    tilt_dir = direction

            # Drawing
            self._nebula.update(dt)
            self._nebula.draw(self.screen)

            # Draw Title
            title = self._font_title.render("SELECT PLAY TARGET", True, (255, 255, 255))
            self.screen.blit(title, title.get_rect(center=(self._W // 2, int(60 * self._sc))))

            sub = self._font_sub.render(
                "tilt or arrow keys to choose   •   flick / enter / click to confirm",
                True, (165, 165, 180)
            )
            self.screen.blit(sub, sub.get_rect(center=(self._W // 2, int(105 * self._sc))))

            # Draw Cards
            for i, (title_text, _, lines, accent) in enumerate(self.options):
                rect = self._card_rects[i]
                is_sel = (i == self.selected_idx)

                # Card BG
                pygame.draw.rect(self.screen, (30, 30, 52), rect, border_radius=10)

                # Selected glow & borders
                if is_sel:
                    # Glow
                    for extra, alpha in ((int(14*self._sc), 35), (int(9*self._sc), 22), (int(4*self._sc), 12)):
                        gw = rect.width + extra * 2
                        gh = rect.height + extra * 2
                        gsurf = pygame.Surface((gw, gh), pygame.SRCALPHA)
                        gclr = (*accent, alpha)
                        pygame.draw.rect(gsurf, gclr, gsurf.get_rect(), border_radius=14)
                        self.screen.blit(gsurf, (rect.left - extra, rect.top - extra))
                    border_clr = accent
                    border_w = 3
                else:
                    border_clr = tuple(max(0, c - 120) for c in accent)
                    border_w = 2

                pygame.draw.rect(self.screen, border_clr, rect, border_w, border_radius=10)

                # Card Title
                card_title_surf = self._font_card.render(title_text, True, accent if is_sel else (165, 165, 180))
                self.screen.blit(card_title_surf, card_title_surf.get_rect(
                    centerx=rect.centerx, top=rect.top + int(20 * self._sc)
                ))

                # Card description
                for j, line in enumerate(lines):
                    clr = (255, 255, 255) if is_sel else (165, 165, 180)
                    surf = self._font_desc.render(line, True, clr)
                    self.screen.blit(surf, surf.get_rect(
                        centerx=rect.centerx,
                        top=rect.top + int(100 * self._sc) + j * int(22 * self._sc)
                    ))

            # Draw Exit Hint at bottom
            hint = self._font_sub.render("Press ESC to return to Home Screen", True, (150, 150, 160))
            self.screen.blit(hint, hint.get_rect(center=(self._W // 2, self._H - int(60 * self._sc))))

            pygame.display.flip()


# ── FireworksCelebration ──────────────────────────────────────────────────────

class FireworkParticle:
    def __init__(self, x: float, y: float, color: Tuple[int, int, int]):
        self.x = x
        self.y = y
        angle = random.uniform(0, 2 * math.pi)
        speed = random.uniform(50, 250)
        self.vx = math.cos(angle) * speed
        self.vy = math.sin(angle) * speed
        self.color = color
        self.alpha = 255.0
        self.decay = random.uniform(100, 200) # alpha decay per second
        self.gravity = 150.0

    def update(self, dt: float) -> bool:
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.vy += self.gravity * dt
        self.alpha = max(0.0, self.alpha - self.decay * dt)
        return self.alpha > 0


class FireworksCelebration:
    def __init__(self, W: int, H: int, username: str, score: int):
        self.W = W
        self.H = H
        self.username = username
        self.score = score
        self.particles: List[FireworkParticle] = []
        self.timer = 2.5 # 2.5 seconds duration
        self.spawn_timer = 0.0
        
        # Predefined list of appreciation messages
        appreciations = [
            "Spectacular job", "Outstanding", "Incredible play", 
            "Amazing effort", "Fantastic skill", "Superb movement"
        ]
        self.msg = f"{random.choice(appreciations)}, {username or 'Player'}!"
        self._spawn_burst()

    def _spawn_burst(self):
        cx = random.randint(int(self.W * 0.2), int(self.W * 0.8))
        cy = random.randint(int(self.H * 0.2), int(self.H * 0.6))
        color = random.choice([
            (255, 50, 50), (50, 255, 50), (50, 50, 255),
            (255, 255, 50), (255, 50, 255), (50, 255, 255),
            (255, 150, 50)
        ])
        for _ in range(60):
            self.particles.append(FireworkParticle(cx, cy, color))

    def update(self, dt: float) -> bool:
        self.timer -= dt
        self.spawn_timer -= dt
        if self.spawn_timer <= 0 and self.timer > 0.5:
            self._spawn_burst()
            self.spawn_timer = 0.4

        # Update particles
        alive_particles = []
        for p in self.particles:
            if p.update(dt):
                alive_particles.append(p)
        self.particles = alive_particles

        return self.timer > 0

    def draw(self, screen: pygame.Surface, font_large: pygame.font.Font, font_small: pygame.font.Font) -> None:
        # Draw semi-transparent dim overlay first
        dim_surf = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        dim_surf.fill((10, 10, 20, 120))
        screen.blit(dim_surf, (0, 0))

        # Draw particles
        for p in self.particles:
            p_color = (*p.color, int(p.alpha))
            p_surf = pygame.Surface((8, 8), pygame.SRCALPHA)
            pygame.draw.circle(p_surf, p_color, (4, 4), 3)
            screen.blit(p_surf, (int(p.x) - 4, int(p.y) - 4))

        # Draw appreciation text
        t_surf = font_large.render(self.msg, True, (255, 215, 0)) # Gold text
        screen.blit(t_surf, t_surf.get_rect(center=(self.W // 2, self.H // 2 - 30)))

        s_surf = font_small.render(f"You reached {self.score} points!", True, (255, 255, 255))
        screen.blit(s_surf, s_surf.get_rect(center=(self.W // 2, self.H // 2 + 30)))


# ── GameExitAppreciationScreen ────────────────────────────────────────────────

class GameExitAppreciationScreen:
    def __init__(self, screen: pygame.Surface, clock: pygame.time.Clock, username: str, score: int):
        self.screen = screen
        self.clock = clock
        self.username = username
        self.score = score
        self._W, self._H = screen.get_size()
        sc = min(self._W / 800, self._H / 600)
        self._sc = sc
        self._font_title = pygame.font.SysFont("Arial", max(24, int(48 * sc)), bold=True)
        self._font_score = pygame.font.SysFont("Arial", max(20, int(36 * sc)), bold=True)
        self._font_msg   = pygame.font.SysFont("Arial", max(14, int(24 * sc)))
        self._font_hint  = pygame.font.SysFont("Arial", max(10, int(16 * sc)))
        self._nebula     = NebulaBg()

        appreciations = [
            "Spectacular job", "Outstanding", "Incredible play", 
            "Amazing effort", "Fantastic skill", "Superb movement"
        ]
        self.msg = f"{random.choice(appreciations)}, {username or 'Player'}!"

    def run(self, gesture_src=None) -> None:
        pygame.mouse.set_visible(True)
        t = 0.0
        # Wait a tiny bit to prevent accidental immediately skip from previous keys/clicks
        time.sleep(0.15)
        pygame.event.clear()

        while True:
            dt = self.clock.tick(60) / 1000.0
            t += dt

            # Handle events
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return
                if event.type == pygame.KEYDOWN:
                    if event.key in (pygame.K_ESCAPE, pygame.K_RETURN, pygame.K_SPACE):
                        return
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    return

            # Handle gesture source
            if gesture_src is not None:
                gs = gesture_src.get_state()
                if gs.calibrated and gs.launch:
                    return

            # Draw background
            self._nebula.update(dt)
            self._nebula.draw(self.screen)

            # Draw title
            title_surf = self._font_title.render("SESSION COMPLETE", True, (255, 215, 0))
            self.screen.blit(title_surf, title_surf.get_rect(center=(self._W // 2, self._H // 3)))

            # Draw score
            score_surf = self._font_score.render(f"Final Score: {self.score}", True, (255, 255, 255))
            self.screen.blit(score_surf, score_surf.get_rect(center=(self._W // 2, self._H // 2)))

            # Draw appreciation message
            msg_surf = self._font_msg.render(self.msg, True, (100, 240, 120))
            self.screen.blit(msg_surf, msg_surf.get_rect(center=(self._W // 2, self._H // 2 + 60)))

            # Draw flashing prompt/hint
            if int(t * 2) % 2 == 0:
                hint_surf = self._font_hint.render("Press ESC, Space, Gesture Flick, or Click to Continue", True, (150, 150, 160))
                self.screen.blit(hint_surf, hint_surf.get_rect(center=(self._W // 2, self._H - 80)))

            pygame.display.flip()
