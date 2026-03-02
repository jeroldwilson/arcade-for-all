"""
home.py — Game selection home screen

Displays two game cards (Bricks, Snake) and lets the player choose with:
  • Sensor tilt left/right — navigate between cards
  • Sensor flick (launch) — confirm selection
  • Mouse hover / click    — highlight and select
  • LEFT / RIGHT arrows    — navigate
  • ENTER / SPACE          — confirm selection
  • ESC                    — quit application
"""

import math
import sys
from typing import List, Optional, Tuple

import pygame


# ── Dimensions ────────────────────────────────────────────────────────────────
W, H       = 800, 600
FPS        = 60
CARD_W     = 340
CARD_H     = 280
CARD_GAP   = 60
CARD_Y     = 155
MARGIN     = (W - 2 * CARD_W - CARD_GAP) // 2  # 30 px each side

# ── Colours ───────────────────────────────────────────────────────────────────
BG         = (15,  15,  25)
TEXT_CLR   = (220, 220, 220)
DIM_CLR    = (90,  90, 100)
CARD_BG    = (22,  22,  38)

# ── Game metadata ─────────────────────────────────────────────────────────────
GAMES = ["bricks", "snake"]

GAME_META = {
    "bricks": {
        "title":  "BRICKS",
        "desc":   ["Break all the bricks!", "Tilt wrist to move paddle.", "Flick to launch ball."],
        "accent": (80, 180, 255),
    },
    "snake": {
        "title":  "SNAKE",
        "desc":   ["Eat food, grow longer!", "Tilt wrist to steer.", "Avoid walls and yourself."],
        "accent": (80, 220, 100),
    },
}

# Tilt navigation thresholds / timing
TILT_THRESHOLD   = 0.55   # paddle_velocity magnitude to trigger navigation
TILT_INITIAL_CD  = 1.20   # seconds before first repeat
TILT_REPEAT_CD   = 1.00   # seconds between repeats when held


class HomeScreen:
    """
    Renders the game selection menu and blocks until a game is chosen.
    Accepts an existing pygame surface and clock (owned by main.py).
    """

    def __init__(self, screen: pygame.Surface, clock: pygame.time.Clock):
        self._screen = screen
        self._clock  = clock

        self._font_title = pygame.font.SysFont("monospace", 42, bold=True)
        self._font_sub   = pygame.font.SysFont("monospace", 14)
        self._font_card  = pygame.font.SysFont("monospace", 28, bold=True)
        self._font_desc  = pygame.font.SysFont("monospace", 14)

        # Pre-compute card rects
        self._card_rects: List[pygame.Rect] = []
        for i in range(len(GAMES)):
            x = MARGIN + i * (CARD_W + CARD_GAP)
            self._card_rects.append(pygame.Rect(x, CARD_Y, CARD_W, CARD_H))

        self._selected_idx: int = 0
        self._hover_idx: Optional[int] = None

        # Tilt navigation state
        self._tilt_dir: int   = 0    # -1, 0, +1
        self._tilt_cd: float  = 0.0  # seconds until next tilt nav

        # Glow animation
        self._glow_phase: float = 0.0

    # ── Public entry point ─────────────────────────────────────────────────────

    def run(self, gesture_src) -> str:
        """Block until a game is selected. Returns game name string."""
        pygame.mouse.set_visible(True)
        while True:
            dt = self._clock.tick(FPS) / 1000.0
            self._glow_phase = (self._glow_phase + dt * 2.5) % (2 * math.pi)
            self._tilt_cd = max(0.0, self._tilt_cd - dt)

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit()
                    sys.exit(0)
                result = self._handle_event(event)
                if result:
                    return result

            self._update_hover()
            result = self._handle_gesture(gesture_src)
            if result:
                return result

            self._draw()
            pygame.display.flip()

    # ── Input handling ────────────────────────────────────────────────────────

    def _handle_event(self, event: pygame.event.Event) -> Optional[str]:
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_LEFT:
                self._navigate(-1)
            elif event.key == pygame.K_RIGHT:
                self._navigate(1)
            elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
                return GAMES[self._selected_idx]
            elif event.key == pygame.K_ESCAPE:
                pygame.quit()
                sys.exit(0)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._hover_idx is not None:
                return GAMES[self._hover_idx]
        return None

    def _update_hover(self) -> None:
        mx, my = pygame.mouse.get_pos()
        self._hover_idx = None
        for i, rect in enumerate(self._card_rects):
            if rect.collidepoint(mx, my):
                self._hover_idx = i
                self._selected_idx = i
                break

    def _handle_gesture(self, gesture_src) -> Optional[str]:
        if gesture_src is None:
            return None
        gs = gesture_src.get_state()
        if not gs.calibrated:
            return None

        # Flick (launch gesture) confirms selection
        if gs.launch:
            return GAMES[self._selected_idx]

        # Tilt left/right navigates cards
        direction = 0
        if gs.paddle_velocity < -TILT_THRESHOLD:
            direction = -1
        elif gs.paddle_velocity > TILT_THRESHOLD:
            direction = 1

        if direction != 0:
            if direction != self._tilt_dir:
                # New direction — navigate immediately and set initial cooldown
                self._navigate(direction)
                self._tilt_dir = direction
                self._tilt_cd  = TILT_INITIAL_CD
            elif self._tilt_cd <= 0:
                # Same direction held — repeat navigate
                self._navigate(direction)
                self._tilt_cd = TILT_REPEAT_CD
        else:
            self._tilt_dir = 0
            self._tilt_cd  = 0.0

        return None

    def _navigate(self, direction: int) -> None:
        self._selected_idx = (self._selected_idx + direction) % len(GAMES)

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _draw(self) -> None:
        self._screen.fill(BG)
        self._draw_title()
        for i, game_id in enumerate(GAMES):
            self._draw_card(i, game_id)
        self._draw_hint()

    def _draw_title(self) -> None:
        title = self._font_title.render("SELECT YOUR GAME", True, TEXT_CLR)
        self._screen.blit(title, title.get_rect(center=(W // 2, 60)))
        sub = self._font_sub.render(
            "tilt or arrow keys to choose   •   flick / enter / click to play",
            True, DIM_CLR
        )
        self._screen.blit(sub, sub.get_rect(center=(W // 2, 105)))

    def _draw_card(self, idx: int, game_id: str) -> None:
        rect   = self._card_rects[idx]
        meta   = GAME_META[game_id]
        accent = meta["accent"]
        is_sel = (idx == self._selected_idx)

        # Card background
        pygame.draw.rect(self._screen, CARD_BG, rect, border_radius=10)

        if is_sel:
            self._draw_glow(rect, accent)
            border_clr = accent
            border_w   = 3
        else:
            border_clr = tuple(max(0, c - 120) for c in accent)  # type: ignore
            border_w   = 2

        pygame.draw.rect(self._screen, border_clr, rect, border_w, border_radius=10)

        # Game title
        title_surf = self._font_card.render(meta["title"], True,
                                            accent if is_sel else DIM_CLR)
        self._screen.blit(title_surf, title_surf.get_rect(
            centerx=rect.centerx, top=rect.top + 18
        ))

        # Thumbnail preview
        preview_rect = pygame.Rect(rect.left + 20, rect.top + 65, CARD_W - 40, 130)
        self._draw_preview(game_id, preview_rect, accent, is_sel)

        # Description lines
        for j, line in enumerate(meta["desc"]):
            clr  = TEXT_CLR if is_sel else DIM_CLR
            surf = self._font_desc.render(line, True, clr)
            self._screen.blit(surf, surf.get_rect(
                centerx=rect.centerx,
                top=rect.top + 210 + j * 20
            ))

    def _draw_glow(self, rect: pygame.Rect, accent: Tuple[int, int, int]) -> None:
        brightness = int(180 + 60 * math.sin(self._glow_phase))
        for extra, alpha in ((14, 35), (9, 22), (4, 12)):
            gw = rect.width  + extra * 2
            gh = rect.height + extra * 2
            gsurf = pygame.Surface((gw, gh), pygame.SRCALPHA)
            gclr  = (accent[0], accent[1], accent[2], alpha)
            pygame.draw.rect(gsurf, gclr, gsurf.get_rect(), border_radius=14)
            self._screen.blit(gsurf, (rect.left - extra, rect.top - extra))

    def _draw_preview(
        self,
        game_id: str,
        area: pygame.Rect,
        accent: Tuple[int, int, int],
        active: bool,
    ) -> None:
        # Clip preview drawing to the area rect
        prev_clip = self._screen.get_clip()
        self._screen.set_clip(area)

        pygame.draw.rect(self._screen, (10, 10, 20), area, border_radius=6)

        dim = 180 if active else 100

        if game_id == "bricks":
            self._draw_bricks_preview(area, dim)
        elif game_id == "snake":
            self._draw_snake_preview(area, dim)

        self._screen.set_clip(prev_clip)

    def _draw_bricks_preview(self, area: pygame.Rect, dim: int) -> None:
        PALETTE = [
            (220, 60, 60), (240, 160, 40), (60, 200, 100),
            (60, 140, 240), (180, 60, 220), (240, 240, 60),
        ]
        bw, bh = 36, 14
        cols, rows = 7, 4
        pad_x = (area.width  - cols * bw) // 2
        pad_y = 8
        for row in range(rows):
            for col in range(cols):
                base = PALETTE[row % len(PALETTE)]
                clr  = tuple(min(255, int(c * dim / 255)) for c in base)
                bx = area.left + pad_x + col * bw + 2
                by = area.top  + pad_y + row * (bh + 2)
                pygame.draw.rect(self._screen, clr, (bx, by, bw - 2, bh), border_radius=2)

        # Paddle
        px = area.centerx - 30
        py = area.bottom - 18
        pygame.draw.rect(self._screen, (min(255, dim), min(255, int(dim * 0.7)), 255),
                         (px, py, 60, 8), border_radius=4)

        # Ball
        bx2 = area.centerx + 10
        by2 = area.bottom - 32
        pygame.draw.circle(self._screen, (dim, dim, dim), (bx2, by2), 5)

    def _draw_snake_preview(self, area: pygame.Rect, dim: int) -> None:
        CELL = 14
        # Subtle grid
        for x in range(area.left, area.right, CELL):
            pygame.draw.line(self._screen, (30, 30, 50), (x, area.top), (x, area.bottom))
        for y in range(area.top, area.bottom, CELL):
            pygame.draw.line(self._screen, (30, 30, 50), (area.left, y), (area.right, y))

        # Snake body — an L-shaped path
        snake_cells = [
            (8, 4), (7, 4), (6, 4), (5, 4), (4, 4), (4, 5), (4, 6),
        ]
        ox = area.left + 10
        oy = area.top  + 10
        for i, (cx, cy) in enumerate(snake_cells):
            r = pygame.Rect(ox + cx * CELL + 1, oy + cy * CELL + 1, CELL - 2, CELL - 2)
            if i == 0:
                clr = (min(255, int(140 * dim / 255)),
                       255,
                       min(255, int(140 * dim / 255)))
            else:
                clr = (min(255, int(80 * dim / 255)),
                       min(255, int(220 * dim / 255)),
                       min(255, int(100 * dim / 255)))
            pygame.draw.rect(self._screen, clr, r, border_radius=3)

        # Food
        fx = ox + 11 * CELL + 2
        fy = oy + 4  * CELL + 2
        pygame.draw.rect(self._screen, (255, min(255, int(80 * dim / 255)), min(255, int(80 * dim / 255))),
                         (fx, fy, CELL - 4, CELL - 4), border_radius=CELL // 2)

    def _draw_hint(self) -> None:
        controls = [
            ("Sensor", "tilt to choose • flick to play"),
            ("Mouse",  "hover to choose • click to play"),
            ("Keys",   "← → to choose • Enter to play"),
        ]
        y = CARD_Y + CARD_H + 20
        for label, text in controls:
            line = f"{label}: {text}"
            surf = self._font_sub.render(line, True, DIM_CLR)
            self._screen.blit(surf, surf.get_rect(center=(W // 2, y)))
            y += 18
