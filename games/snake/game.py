"""
snake/game.py — Classic Snake game (pygame)

Controls
────────
  Sensor mode  : Tilt wrist LEFT/RIGHT to turn left/right.
                 Tilt wrist FORWARD/BACK to turn up/down.
  Keyboard mode: Arrow keys for all 4 directions.
  Both modes   : ESC = pause / back to menu, R = restart, H = home.

Design decisions
────────────────
- 800×600 grid with 20px cells (40 columns × 30 rows).
- Snake speed increases slightly each time food is eaten.
- Sensor gesture uses edge-triggered debounce: one tilt crossing = one turn.
- Keyboard UP/DOWN are read directly from pygame.key.get_pressed() since
  KeyboardFallback only exposes left/right tilt.
"""

import random
import sys
from collections import deque
from enum import Enum
from typing import Optional, Tuple, TYPE_CHECKING

import pygame

if TYPE_CHECKING:
    from shared.gesture import GestureState

# ── Constants ─────────────────────────────────────────────────────────────────
W, H           = 800, 600
FPS            = 60
CELL           = 20
COLS           = W // CELL   # 40
ROWS           = H // CELL   # 30
MOVE_INTERVAL  = 0.12        # seconds per grid step (base)
MIN_INTERVAL   = 0.05        # fastest possible
SPEED_FACTOR   = 0.005       # shaved off interval per food eaten
TILT_THRESH    = 0.35        # gesture threshold to register a direction change

# ── Colours ───────────────────────────────────────────────────────────────────
BG          = (15,  15,  25)
GRID_CLR    = (25,  25,  40)
SNAKE_CLR   = (80,  220, 100)
SNAKE_HEAD  = (140, 255, 140)
FOOD_CLR    = (255, 80,  80)
TEXT_CLR    = (220, 220, 220)
DIM_CLR     = (90,  90,  100)


# ── Direction enum ────────────────────────────────────────────────────────────

class Dir(Enum):
    UP    = (0, -1)
    DOWN  = (0,  1)
    LEFT  = (-1, 0)
    RIGHT = (1,  0)

    def opposite(self) -> "Dir":
        return {
            Dir.UP:    Dir.DOWN,
            Dir.DOWN:  Dir.UP,
            Dir.LEFT:  Dir.RIGHT,
            Dir.RIGHT: Dir.LEFT,
        }[self]


# ── Game class ────────────────────────────────────────────────────────────────

class SnakeGame:
    """
    Classic Snake game using the same gesture/keyboard infrastructure.

    Accepts an existing pygame display surface and clock (owned by main.py).
    Returns "home" when the player exits to the selection screen.
    """

    def __init__(
        self,
        screen: pygame.Surface,
        clock: pygame.time.Clock,
        debug: bool = False,
    ):
        self._screen = screen
        self._clock  = clock
        self._debug  = debug

        self._font_lg = pygame.font.SysFont("monospace", 48, bold=True)
        self._font_md = pygame.font.SysFont("monospace", 24)
        self._font_sm = pygame.font.SysFont("monospace", 14)

        self._gesture_src = None
        self._reset()

    # ── Public entry point ─────────────────────────────────────────────────────

    def run(self, gesture_src) -> str:
        """Run the game loop. Returns 'home' when player exits to menu."""
        self._gesture_src = gesture_src
        self._reset()
        pygame.mouse.set_visible(True)
        while True:
            dt = self._clock.tick(FPS) / 1000.0
            result = self._handle_events()
            if result:
                return result
            if not self._paused and not self._game_over:
                self._update(dt)
            self._draw()
            pygame.display.flip()

    # ── State management ───────────────────────────────────────────────────────

    def _reset(self) -> None:
        # Start in the middle, moving right, 3 cells long
        cx, cy = COLS // 2, ROWS // 2
        self._body: deque = deque([
            (cx, cy), (cx - 1, cy), (cx - 2, cy)
        ])
        self._direction   = Dir.RIGHT
        self._next_dir    = Dir.RIGHT
        self._score       = 0
        self._game_over   = False
        self._paused      = False
        self._move_timer  = 0.0
        self._move_interval = MOVE_INTERVAL
        self._food        = self._spawn_food()

        # Gesture debounce state
        self._last_tilt_x: int = 0   # -1, 0, +1
        self._last_tilt_y: int = 0

    def _spawn_food(self) -> Tuple[int, int]:
        """Randomly place food on an empty cell."""
        occupied = set(self._body) if hasattr(self, '_body') else set()
        while True:
            pos = (random.randint(0, COLS - 1), random.randint(0, ROWS - 1))
            if pos not in occupied:
                return pos

    # ── Direction input ────────────────────────────────────────────────────────

    def _apply_direction(self, new_dir: Dir) -> None:
        """Buffer a direction change; reject 180° reversals."""
        if new_dir != self._direction.opposite():
            self._next_dir = new_dir

    def _read_gesture(self) -> None:
        """Map GestureState tilt to a direction change (edge-triggered)."""
        if self._gesture_src is None:
            return
        gs = self._gesture_src.get_state()
        if not gs.calibrated:
            return

        # Horizontal tilt → LEFT / RIGHT
        tilt_x = 0
        if gs.paddle_velocity < -TILT_THRESH:
            tilt_x = -1
        elif gs.paddle_velocity > TILT_THRESH:
            tilt_x = 1

        if tilt_x != 0 and tilt_x != self._last_tilt_x:
            self._apply_direction(Dir.LEFT if tilt_x < 0 else Dir.RIGHT)
        self._last_tilt_x = tilt_x

        # Vertical tilt → UP / DOWN
        tilt_y = 0
        if gs.tilt_y < -TILT_THRESH:
            tilt_y = -1   # forward tilt → UP
        elif gs.tilt_y > TILT_THRESH:
            tilt_y = 1    # back tilt → DOWN

        if tilt_y != 0 and tilt_y != self._last_tilt_y:
            self._apply_direction(Dir.UP if tilt_y < 0 else Dir.DOWN)
        self._last_tilt_y = tilt_y

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

        # Handle held arrow keys for keyboard direction control
        keys = pygame.key.get_pressed()
        if keys[pygame.K_UP]:
            self._apply_direction(Dir.UP)
        elif keys[pygame.K_DOWN]:
            self._apply_direction(Dir.DOWN)
        elif keys[pygame.K_LEFT]:
            self._apply_direction(Dir.LEFT)
        elif keys[pygame.K_RIGHT]:
            self._apply_direction(Dir.RIGHT)

        # Feed left/right to KeyboardFallback so paddle_velocity is set
        src = self._gesture_src
        if hasattr(src, "press_left"):
            if keys[pygame.K_LEFT]:
                src.press_left()
            else:
                src.release_left()
            if keys[pygame.K_RIGHT]:
                src.press_right()
            else:
                src.release_right()

        return None

    def _on_key(self, key: int) -> Optional[str]:
        if key == pygame.K_ESCAPE:
            if self._game_over:
                return "home"
            self._paused = not self._paused
        elif key == pygame.K_r and self._game_over:
            self._reset()
        elif key == pygame.K_h and self._game_over:
            return "home"
        elif key == pygame.K_f:
            pygame.display.toggle_fullscreen()
        return None

    # ── Update ────────────────────────────────────────────────────────────────

    def _update(self, dt: float) -> None:
        self._read_gesture()

        self._move_timer += dt
        if self._move_timer >= self._move_interval:
            self._move_timer -= self._move_interval
            self._step()

    def _step(self) -> None:
        head = self._body[0]
        dx, dy = self._next_dir.value
        new_head = (head[0] + dx, head[1] + dy)
        self._direction = self._next_dir

        # Wall collision
        if not (0 <= new_head[0] < COLS and 0 <= new_head[1] < ROWS):
            self._game_over = True
            return

        # Self collision
        if new_head in self._body:
            self._game_over = True
            return

        self._body.appendleft(new_head)

        # Food eaten
        if new_head == self._food:
            self._score += 10
            self._food = self._spawn_food()
            self._move_interval = max(MIN_INTERVAL, self._move_interval - SPEED_FACTOR)
        else:
            self._body.pop()

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _draw(self) -> None:
        self._screen.fill(BG)
        self._draw_grid()
        self._draw_food()
        self._draw_snake()
        self._draw_hud()
        if self._debug:
            self._draw_debug()
        if self._paused:
            self._draw_overlay("PAUSED", "ESC to resume")
        if self._game_over:
            self._draw_overlay(
                "GAME OVER",
                f"Score: {self._score}   R=restart   ESC/H=menu"
            )

    def _draw_grid(self) -> None:
        for x in range(0, W, CELL):
            pygame.draw.line(self._screen, GRID_CLR, (x, 0), (x, H))
        for y in range(0, H, CELL):
            pygame.draw.line(self._screen, GRID_CLR, (0, y), (W, y))

    def _draw_snake(self) -> None:
        for i, (cx, cy) in enumerate(self._body):
            rect = pygame.Rect(cx * CELL + 1, cy * CELL + 1, CELL - 2, CELL - 2)
            color = SNAKE_HEAD if i == 0 else SNAKE_CLR
            pygame.draw.rect(self._screen, color, rect, border_radius=4)

    def _draw_food(self) -> None:
        fx, fy = self._food
        rect = pygame.Rect(fx * CELL + 2, fy * CELL + 2, CELL - 4, CELL - 4)
        pygame.draw.rect(self._screen, FOOD_CLR, rect, border_radius=CELL // 2)

    def _draw_hud(self) -> None:
        score_surf = self._font_md.render(f"Score: {self._score}", True, TEXT_CLR)
        self._screen.blit(score_surf, (12, 8))
        speed_label = self._font_sm.render(
            f"Speed: {1.0 / self._move_interval:.1f} steps/s", True, DIM_CLR
        )
        self._screen.blit(speed_label, (W // 2 - 60, 10))
        len_label = self._font_sm.render(
            f"Length: {len(self._body)}", True, DIM_CLR
        )
        self._screen.blit(len_label, (W - 120, 10))

    def _draw_debug(self) -> None:
        if self._gesture_src is None:
            return
        gs = self._gesture_src.get_state()
        lines = [
            f"paddle_vel : {gs.paddle_velocity:+.3f}",
            f"tilt_y     : {gs.tilt_y:+.3f}",
            f"calibrated : {gs.calibrated}",
            f"direction  : {self._direction.name}",
            f"next_dir   : {self._next_dir.name}",
        ]
        for i, line in enumerate(lines):
            surf = self._font_sm.render(line, True, (180, 220, 180))
            self._screen.blit(surf, (10, H - 90 + i * 16))

    def _draw_overlay(self, title: str, subtitle: str = "") -> None:
        dim = pygame.Surface((W, H), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 160))
        self._screen.blit(dim, (0, 0))
        t = self._font_lg.render(title, True, TEXT_CLR)
        self._screen.blit(t, t.get_rect(center=(W // 2, H // 2 - 30)))
        if subtitle:
            s = self._font_md.render(subtitle, True, DIM_CLR)
            self._screen.blit(s, s.get_rect(center=(W // 2, H // 2 + 20)))
