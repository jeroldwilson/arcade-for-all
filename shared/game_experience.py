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
            bright = tuple(min(255, c + random.randint(-30, 60)) for c in color)
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
            bright = tuple(min(255, c + random.randint(-20, 60)) for c in color)
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
    def __init__(self, screen: pygame.Surface, clock: pygame.time.Clock):
        self.screen       = screen
        self.clock        = clock
        self._font_large  = pygame.font.SysFont("Arial", 64, bold=True)
        self._font        = pygame.font.SysFont("Arial", 36)
        self.options      = [
            ("Score Target: 200",  GameGoal(target_score=200)),
            ("Score Target: 500",  GameGoal(target_score=500)),
            ("Time Limit: 2 Min", GameGoal(target_time_sec=120)),
            ("Time Limit: 5 Min", GameGoal(target_time_sec=300)),
            ("Endless (10k Score)", GameGoal(target_score=10000)),
        ]
        self.selected_idx = 0

    def run(self) -> GameGoal:
        W, H = self.screen.get_size()
        while True:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return GameGoal()
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_UP:
                        self.selected_idx = (self.selected_idx - 1) % len(self.options)
                    elif event.key == pygame.K_DOWN:
                        self.selected_idx = (self.selected_idx + 1) % len(self.options)
                    elif event.key == pygame.K_RETURN:
                        return self.options[self.selected_idx][1]
            self.screen.fill((20, 20, 30))
            title = self._font_large.render("Select Game Goal", True, (255, 255, 255))
            self.screen.blit(title, title.get_rect(center=(W // 2, H // 4)))
            start_y = H // 2 - 50
            for i, (text, _) in enumerate(self.options):
                color  = (0, 255, 100) if i == self.selected_idx else (150, 150, 150)
                prefix = "▶ " if i == self.selected_idx else "  "
                surf   = self._font.render(prefix + text, True, color)
                self.screen.blit(surf, surf.get_rect(center=(W // 2, start_y + i * 50)))
            pygame.display.flip()
            self.clock.tick(60)
