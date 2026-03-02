"""
game.py — Bricks & Paddle game (pygame)

Controls
────────
  Sensor mode  : Tilt wrist left/right to move paddle.
                 Flick wrist up to launch ball.
  Keyboard mode: ← / → arrow keys move the paddle.
                 SPACE launches the ball.
  Both modes   : ESC = pause / back to menu (when game over), R = restart.

Design decisions
────────────────
- Resolution independent: internal render size 800×600, scaled to window.
- Paddle speed is proportional to GestureState.paddle_velocity [-1 … 1].
- Ball spin (GestureState.spin) adds a lateral velocity nudge on each
  paddle bounce, letting skilled players aim with wrist rotation.
- Bricks have 1–3 hit points mapped to visible colour.
- Power-ups drop occasionally: WIDE (wider paddle), MULTI (extra ball),
  FAST (speed boost/penalty).
"""

import math
import random
import sys
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, TYPE_CHECKING

import pygame

if TYPE_CHECKING:
    from shared.gesture import GestureState

# ── Dimensions & constants ────────────────────────────────────────────────────
W, H          = 800, 600
FPS           = 60
PADDLE_W      = 100
PADDLE_H      = 14
PADDLE_Y      = H - 50
PADDLE_SPEED  = 420        # pixels/sec at full velocity

BALL_R        = 9
BALL_SPEED    = 340        # pixels/sec initial

BRICK_COLS    = 12
BRICK_ROWS    = 6
BRICK_W       = W // BRICK_COLS
BRICK_H       = 22
BRICK_TOP     = 60
BRICK_GAP     = 2

LIVES_START   = 3
POWERUP_PROB  = 0.15       # chance a destroyed brick drops a power-up

# ── Colours ───────────────────────────────────────────────────────────────────
BG           = (15,  15,  25)
PADDLE_CLR   = (80, 180, 255)
BALL_CLR     = (255, 255, 255)
TEXT_CLR     = (220, 220, 220)
DIM_CLR      = (90,  90, 100)
POWERUP_CLRS = {
    "WIDE":  (100, 255, 120),
    "MULTI": (255, 220,  60),
    "FAST":  (255,  80,  80),
}
BRICK_PALETTE = [
    # hp=1         hp=2          hp=3
    (220,  60,  60),
    (240, 160,  40),
    ( 60, 200, 100),
    ( 60, 140, 240),
    (180,  60, 220),
    (240, 240,  60),
]

def _brick_colour(row: int, hp: int) -> Tuple[int, int, int]:
    base = BRICK_PALETTE[row % len(BRICK_PALETTE)]
    factor = 0.55 + 0.45 * (hp / 3)
    return tuple(max(0, min(255, int(c * factor))) for c in base)  # type: ignore


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class Brick:
    rect: pygame.Rect
    hp:   int
    row:  int

    @property
    def alive(self) -> bool:
        return self.hp > 0

    def hit(self) -> int:
        """Reduce HP by 1; return points scored."""
        self.hp -= 1
        return (3 - self.hp) * 10 + 10

    def draw(self, surf: pygame.Surface) -> None:
        if not self.alive:
            return
        colour = _brick_colour(self.row, self.hp)
        pygame.draw.rect(surf, colour, self.rect, border_radius=3)
        pygame.draw.rect(surf, (0, 0, 0), self.rect, 1, border_radius=3)


@dataclass
class Ball:
    x: float
    y: float
    vx: float
    vy: float
    active: bool = True    # False = waiting to be launched from paddle

    def rect(self) -> pygame.Rect:
        return pygame.Rect(int(self.x) - BALL_R, int(self.y) - BALL_R,
                           BALL_R * 2, BALL_R * 2)

    def draw(self, surf: pygame.Surface) -> None:
        pygame.draw.circle(surf, BALL_CLR, (int(self.x), int(self.y)), BALL_R)
        # Subtle glow
        pygame.draw.circle(surf, (200, 230, 255), (int(self.x), int(self.y)), BALL_R, 2)


@dataclass
class PowerUp:
    rect:  pygame.Rect
    kind:  str
    speed: float = 130.0
    alive: bool  = True

    def update(self, dt: float) -> None:
        self.rect.y += int(self.speed * dt)
        if self.rect.y > H:
            self.alive = False

    def draw(self, surf: pygame.Surface) -> None:
        colour = POWERUP_CLRS.get(self.kind, (200, 200, 200))
        pygame.draw.rect(surf, colour, self.rect, border_radius=4)
        font = pygame.font.SysFont("monospace", 11, bold=True)
        label = font.render(self.kind, True, (0, 0, 0))
        surf.blit(label, label.get_rect(center=self.rect.center))


# ── Game class ────────────────────────────────────────────────────────────────

class BricksGame:
    """
    Self-contained pygame game loop.

    Accepts an existing pygame display surface and clock (owned by main.py).
    Call `run(gesture_source)` where `gesture_source` has a
    `get_state() -> GestureState` method (either GestureInterpreter
    or KeyboardFallback).

    Returns "home" when the player exits back to the selection screen.
    """

    def __init__(
        self,
        screen: pygame.Surface,
        clock: pygame.time.Clock,
        debug: bool = False,
    ):
        self._screen  = screen
        self._clock   = clock
        self._font_lg = pygame.font.SysFont("monospace", 48, bold=True)
        self._font_md = pygame.font.SysFont("monospace", 24)
        self._font_sm = pygame.font.SysFont("monospace", 14)
        self._gesture_source = None
        self._debug_hud = debug

        self._reset()

    # ── Public entry point ─────────────────────────────────────────────────────

    def run(self, gesture_source) -> str:
        """Run the game loop. Returns 'home' when player exits to menu."""
        self._gesture_source = gesture_source
        self._reset()
        pygame.mouse.set_visible(False)
        while True:
            dt = self._clock.tick(FPS) / 1000.0
            result = self._handle_events()
            if result:
                return result
            if not self._paused and not self._game_over and not self._you_win:
                self._update(dt)
            self._draw()
            pygame.display.flip()

    # ── State management ───────────────────────────────────────────────────────

    def _reset(self) -> None:
        self._score     = 0
        self._lives     = LIVES_START
        self._level     = 1
        self._paused    = False
        self._game_over = False
        self._you_win   = False

        self._paddle    = pygame.Rect(
            W // 2 - PADDLE_W // 2, PADDLE_Y, PADDLE_W, PADDLE_H
        )
        self._paddle_w_timer = 0.0   # seconds remaining for WIDE power-up
        self._prev_mouse_x   = pygame.mouse.get_pos()[0]
        self._log_tick       = 0
        self._was_left       = False
        self._was_right      = False

        self._balls: List[Ball]    = []
        self._powerups: List[PowerUp] = []
        self._bricks: List[Brick]  = []

        self._spawn_ball()
        self._build_bricks(self._level)

    def _next_level(self) -> None:
        self._level += 1
        self._powerups.clear()
        self._balls.clear()
        self._spawn_ball()
        self._build_bricks(self._level)

    def _spawn_ball(self) -> None:
        """Create a ball sitting on the paddle, not yet launched."""
        cx = self._paddle.centerx
        self._balls.append(Ball(
            x=cx, y=PADDLE_Y - BALL_R - 1,
            vx=0, vy=0, active=False
        ))

    def _build_bricks(self, level: int) -> None:
        self._bricks.clear()
        # Higher levels → more 2/3-hp bricks
        for row in range(BRICK_ROWS):
            for col in range(BRICK_COLS):
                x = col * BRICK_W + BRICK_GAP
                y = BRICK_TOP + row * (BRICK_H + BRICK_GAP)
                hp_roll = random.random()
                if level >= 3 and hp_roll < 0.25:
                    hp = 3
                elif level >= 2 and hp_roll < 0.40:
                    hp = 2
                else:
                    hp = 1
                self._bricks.append(Brick(
                    rect=pygame.Rect(x, y, BRICK_W - BRICK_GAP, BRICK_H),
                    hp=hp, row=row
                ))

    # ── Event handling ────────────────────────────────────────────────────────

    def _handle_events(self) -> Optional[str]:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit(0)
            elif event.type == pygame.KEYDOWN:
                result = self._on_key(event.key)
                if result:
                    return result

        # Propagate keyboard to KeyboardFallback if that's what's attached
        keys = pygame.key.get_pressed()
        src  = self._gesture_source
        if hasattr(src, "press_left"):
            left_now  = bool(keys[pygame.K_LEFT])
            right_now = bool(keys[pygame.K_RIGHT])
            if left_now != self._was_left:
                self._was_left = left_now
            if right_now != self._was_right:
                self._was_right = right_now
            if left_now:  src.press_left()
            else:         src.release_left()
            if right_now: src.press_right()
            else:         src.release_right()

        return None

    def _on_key(self, key: int) -> Optional[str]:
        if key == pygame.K_ESCAPE:
            if self._game_over or self._you_win:
                return "home"
            else:
                self._paused = not self._paused
        elif key == pygame.K_r and (self._game_over or self._you_win):
            self._reset()
        elif key == pygame.K_d:
            self._debug_hud = not self._debug_hud
        elif key == pygame.K_SPACE:
            self._launch_all_inactive()
        elif key == pygame.K_f:
            # Toggle fullscreen
            pygame.display.toggle_fullscreen()
        # Keyboard fallback: SPACE is also wired through trigger_launch
        src = self._gesture_source
        if key == pygame.K_SPACE and hasattr(src, "trigger_launch"):
            src.trigger_launch()
        return None

    # ── Update ────────────────────────────────────────────────────────────────

    def _update(self, dt: float) -> None:
        gs = self._gesture_source.get_state() if self._gesture_source else None

        self._update_paddle(dt, gs)
        self._update_balls(dt, gs)
        self._update_powerups(dt)
        self._check_win()

    def _update_paddle(self, dt: float, gs) -> None:
        # Apply WIDE power-up timer
        if self._paddle_w_timer > 0:
            self._paddle_w_timer -= dt
            target_w = PADDLE_W * 2
        else:
            target_w = PADDLE_W
        # Smoothly resize
        self._paddle.width += int((target_w - self._paddle.width) * 0.15)

        # Mouse control: if the cursor moved this frame, follow it directly
        mx = pygame.mouse.get_pos()[0]
        velocity = gs.paddle_velocity if gs else 0.0
        if mx != self._prev_mouse_x:
            self._paddle.centerx = mx
            self._prev_mouse_x = mx
        else:
            # Sensor / keyboard velocity fallback
            dx = velocity * PADDLE_SPEED * dt
            self._paddle.x += int(dx)
        self._paddle.x = max(0, min(W - self._paddle.width, self._paddle.x))

        self._log_tick += 1

        # Launch gesture
        if gs and gs.launch:
            self._launch_all_inactive()

    def _launch_all_inactive(self) -> None:
        for ball in self._balls:
            if not ball.active:
                angle = random.uniform(-65, -115)   # upward, slightly randomised
                rad   = math.radians(angle)
                speed = BALL_SPEED + (self._level - 1) * 20
                ball.vx = speed * math.cos(rad)
                ball.vy = speed * math.sin(rad)
                ball.active = True

    def _update_balls(self, dt: float, gs) -> None:
        spin = gs.spin if gs else 0.0
        dead_balls = []

        for ball in self._balls:
            if not ball.active:
                # Ride along the paddle
                ball.x = self._paddle.centerx
                ball.y = PADDLE_Y - BALL_R - 1
                continue

            ball.x += ball.vx * dt
            ball.y += ball.vy * dt

            # Wall collisions
            if ball.x - BALL_R < 0:
                ball.x  = BALL_R
                ball.vx = abs(ball.vx)
            elif ball.x + BALL_R > W:
                ball.x  = W - BALL_R
                ball.vx = -abs(ball.vx)

            if ball.y - BALL_R < 0:
                ball.y  = BALL_R
                ball.vy = abs(ball.vy)

            # Bottom — lose ball
            if ball.y - BALL_R > H:
                dead_balls.append(ball)
                continue

            # Paddle collision
            if ball.rect().colliderect(self._paddle) and ball.vy > 0:
                ball.y  = self._paddle.top - BALL_R
                # Reflect with angle based on hit position
                rel = (ball.x - self._paddle.left) / self._paddle.width  # 0…1
                angle = 150 + rel * (-120)   # 150° left edge → 30° right edge
                speed = math.hypot(ball.vx, ball.vy)
                speed = max(speed, BALL_SPEED)  # never slow down
                rad   = math.radians(angle)
                ball.vx = speed * math.cos(rad) + spin * 80
                ball.vy = -abs(speed * math.sin(rad))

            # Brick collisions
            for brick in self._bricks:
                if not brick.alive:
                    continue
                br = brick.rect
                if not ball.rect().colliderect(br):
                    continue
                pts = brick.hit()
                self._score += pts
                # Determine bounce axis
                overlap_x = min(
                    abs(ball.x - br.left), abs(ball.x - br.right)
                )
                overlap_y = min(
                    abs(ball.y - br.top), abs(ball.y - br.bottom)
                )
                if overlap_x < overlap_y:
                    ball.vx = -ball.vx
                else:
                    ball.vy = -ball.vy
                # Power-up drop
                if not brick.alive and random.random() < POWERUP_PROB:
                    kind = random.choice(["WIDE", "MULTI", "FAST"])
                    pu = PowerUp(
                        rect=pygame.Rect(br.x, br.y, BRICK_W - BRICK_GAP, 14),
                        kind=kind,
                    )
                    self._powerups.append(pu)

        # Remove dead balls
        for b in dead_balls:
            self._balls.remove(b)

        if not self._balls:
            self._lives -= 1
            if self._lives <= 0:
                self._game_over = True
            else:
                self._spawn_ball()

    def _update_powerups(self, dt: float) -> None:
        dead = []
        for pu in self._powerups:
            pu.update(dt)
            if not pu.alive:
                dead.append(pu)
                continue
            if pu.rect.colliderect(self._paddle):
                self._apply_powerup(pu.kind)
                dead.append(pu)
        for pu in dead:
            self._powerups.remove(pu)

    def _apply_powerup(self, kind: str) -> None:
        if kind == "WIDE":
            self._paddle_w_timer = 10.0
        elif kind == "MULTI":
            # Clone every active ball
            new_balls = []
            for ball in self._balls:
                if ball.active:
                    angle_offset = random.choice([-25, 25])
                    rad = math.atan2(ball.vy, ball.vx) + math.radians(angle_offset)
                    speed = math.hypot(ball.vx, ball.vy)
                    new_balls.append(Ball(
                        x=ball.x, y=ball.y,
                        vx=speed * math.cos(rad),
                        vy=speed * math.sin(rad),
                        active=True
                    ))
            self._balls.extend(new_balls)
        elif kind == "FAST":
            for ball in self._balls:
                if ball.active:
                    speed = math.hypot(ball.vx, ball.vy)
                    factor = 0.75  # slow down as a deliberate challenge
                    ball.vx = ball.vx / speed * speed * factor
                    ball.vy = ball.vy / speed * speed * factor

    def _check_win(self) -> None:
        if all(not b.alive for b in self._bricks):
            # Check if more levels exist
            if self._level < 5:
                self._next_level()
            else:
                self._you_win = True

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _draw(self) -> None:
        self._screen.fill(BG)
        self._draw_bricks()
        self._draw_powerups()
        self._draw_balls()
        self._draw_paddle()
        self._draw_hud()
        if self._debug_hud:
            self._draw_debug()
        if self._paused:
            self._draw_overlay("PAUSED", "ESC to resume")
        if self._game_over:
            self._draw_overlay("GAME OVER", f"Score: {self._score}   R=restart   ESC=menu")
        if self._you_win:
            self._draw_overlay("YOU WIN!", f"Final score: {self._score}   R=restart   ESC=menu")

    def _draw_bricks(self) -> None:
        for brick in self._bricks:
            brick.draw(self._screen)

    def _draw_powerups(self) -> None:
        for pu in self._powerups:
            pu.draw(self._screen)

    def _draw_balls(self) -> None:
        for ball in self._balls:
            ball.draw(self._screen)

    def _draw_paddle(self) -> None:
        # Gradient-ish: draw two rects
        pygame.draw.rect(self._screen, PADDLE_CLR, self._paddle, border_radius=6)
        inner = self._paddle.inflate(-4, -4)
        light = tuple(min(255, c + 60) for c in PADDLE_CLR)
        pygame.draw.rect(self._screen, light, inner, border_radius=4)  # type: ignore

    def _draw_hud(self) -> None:
        # Score
        score_surf = self._font_md.render(f"Score: {self._score}", True, TEXT_CLR)
        self._screen.blit(score_surf, (12, 8))
        # Lives
        for i in range(self._lives):
            pygame.draw.circle(
                self._screen, BALL_CLR,
                (W - 20 - i * 22, 18), 7
            )
        # Level
        lvl_surf = self._font_sm.render(f"Level {self._level}", True, DIM_CLR)
        self._screen.blit(lvl_surf, (W // 2 - 30, 10))
        # WIDE timer bar
        if self._paddle_w_timer > 0:
            bar_w = int((self._paddle_w_timer / 10.0) * 120)
            bar_r = pygame.Rect(self._paddle.x, PADDLE_Y + PADDLE_H + 4, bar_w, 4)
            pygame.draw.rect(self._screen, POWERUP_CLRS["WIDE"], bar_r)

    def _draw_debug(self) -> None:
        gs = self._gesture_source.get_state() if self._gesture_source else None
        if gs is None:
            return
        lines = [
            f"ax (smooth) : {gs.raw_ax:+.3f} g",
            f"gz (smooth) : {gs.raw_gz:+.3f} °/s",
            f"paddle vel  : {gs.paddle_velocity:+.3f}",
            f"spin        : {gs.spin:+.3f}",
            f"tilt_y      : {gs.tilt_y:+.3f}",
            f"launch      : {gs.launch}",
        ]
        for i, line in enumerate(lines):
            surf = self._font_sm.render(line, True, (180, 220, 180))
            self._screen.blit(surf, (10, H - 110 + i * 16))

    def _draw_overlay(self, title: str, subtitle: str = "") -> None:
        # Dim background
        dim = pygame.Surface((W, H), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 160))
        self._screen.blit(dim, (0, 0))
        # Title
        t = self._font_lg.render(title, True, TEXT_CLR)
        self._screen.blit(t, t.get_rect(center=(W // 2, H // 2 - 30)))
        # Subtitle
        if subtitle:
            s = self._font_md.render(subtitle, True, DIM_CLR)
            self._screen.blit(s, s.get_rect(center=(W // 2, H // 2 + 20)))
