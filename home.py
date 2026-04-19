"""
home.py — Game selection home screen

Displays game cards and lets the player choose with:
  • Sensor tilt left/right — navigate between cards (scrollable)
  • Sensor flick (launch) — confirm selection
  • Mouse hover / click    — highlight and select
  • LEFT / RIGHT arrows    — navigate / scroll
  • ENTER / SPACE          — confirm selection
  • ESC                    — quit application
  • L / T / R              — hotkeys shown in hint (effective inside games)
"""

import math
import sys
from typing import List, Optional, Tuple

import pygame
from shared.learn_test_support import draw_gesture_debug_overlay


# ── Dimensions ────────────────────────────────────────────────────────────────
W, H       = 800, 600
FPS        = 60
CARD_W     = 200   # fixed card width
CARD_H     = 300
CARD_GAP   = 20
CARD_Y     = 130   # top of cards

VISIBLE_CARDS = 3  # max cards shown at once in the viewport

# ── Colours ───────────────────────────────────────────────────────────────────
BG         = (15,  15,  25)
TEXT_CLR   = (255, 255, 255)
DIM_CLR    = (165, 165, 180)
CARD_BG    = (30,  30,  52)

# ── Game metadata ─────────────────────────────────────────────────────────────
GAMES = ["bricks", "snake", "fruit_ninja"]   # calibration added dynamically

GAME_META = {
    "bricks": {
        "title":   "BRICKS",
        "desc":    ["Break all the bricks!", "Tilt wrist to move paddle.", "Flick to launch ball."],
        "desc_ac": ["Break all the bricks!", "Wider paddle, slower ball.", "Ball bounces — no game over!"],
        "accent":  (110, 200, 255),
    },
    "snake": {
        "title":   "SNAKE",
        "desc":    ["Eat food, grow longer!", "Tilt wrist to steer.", "Avoid walls and yourself."],
        "desc_ac": ["Eat food, grow longer!", "Move wrist — snake finds the way!", "Walls wrap, no game over!"],
        "accent":  (100, 240, 120),
    },
    "fruit_ninja": {
        "title":   "FRUIT SLICE",
        "desc":    ["Slice flying fruits!", "Tilt & flick to swing blade.", "60 seconds, beat your score!"],
        "desc_ac": ["Slice flying fruits!", "Any movement slices!", "Move and have fun!"],
        "accent":  (255, 140, 60),
    },
    "calibration": {
        "title":   "CALIBRATE",
        "desc":    ["Live sensor orientation.", "Pitch · Roll · Yaw view.", "Sensor required."],
        "desc_ac": ["Live sensor orientation.", "Pitch · Roll · Yaw view.", "Sensor required."],
        "accent":  (255, 170, 50),
    },
}

MODE_META = {
    "keyboard":   {"label": "KEYBOARD",              "color": (155, 155, 175)},
    "standard":   {"label": "VEERA (Standard)",      "color": (110, 200, 255)},
    "accessible": {"label": "ASTRA (Accessible)",    "color": (100, 240, 120)},
}

# Tilt navigation thresholds / timing
TILT_THRESHOLD     = 0.55
TILT_NAV_CD        = 1.20
ACC_NAV_CD         = 2.50
ACC_HOLD_REQUIRED  = 0.35


class HomeScreen:
    """
    Renders the scrollable game selection menu and blocks until a game is chosen.
    Accepts an existing pygame surface and clock (owned by main.py).
    """

    def __init__(
        self,
        screen: pygame.Surface,
        clock: pygame.time.Clock,
        mode: str = "standard",
        username: str = "",
        debug: bool = False,
    ):
        self._clock    = clock
        self.mode      = mode
        self._username = username
        self._debug    = debug

        self._games: list = self._compute_games()
        self._selected_idx: int = 0
        self._scroll_offset: int = 0    # index of leftmost visible card
        self._hover_idx: Optional[int] = None

        # Tilt navigation state
        self._tilt_dir: int       = 0
        self._nav_cd: float       = 0.0
        self._acc_hold_dir: int   = 0
        self._acc_hold: float     = 0.0

        # Glow animation
        self._glow_phase: float = 0.0

        self._init_layout(screen)

    def _compute_games(self) -> list:
        games = list(GAMES)
        if self.mode != "keyboard":
            games.append("calibration")
        return games

    def _init_layout(self, screen: pygame.Surface) -> None:
        self._screen = screen
        sw, sh = screen.get_size()
        self._layout_size = (sw, sh)
        self._W  = sw
        self._H  = sh
        self._is_fullscreen = not (sw == 800 and sh == 600)
        sc = min(sw / W, sh / H)
        self._sc = sc

        n_vis = min(len(self._games), VISIBLE_CARDS)
        card_h   = int(CARD_H  * sc)
        card_y   = int(CARD_Y  * sc)
        card_gap = int(CARD_GAP * sc)
        card_w   = int(CARD_W  * sc)

        # Centre the visible cards
        total_w = n_vis * card_w + (n_vis - 1) * card_gap
        margin  = (sw - total_w) // 2

        self._card_w   = card_w
        self._card_h   = card_h
        self._card_y   = card_y
        self._card_gap = card_gap
        self._margin   = margin
        self._n_vis    = n_vis

        self._font_title = pygame.font.SysFont("monospace", max(20, int(42 * sc)), bold=True)
        self._font_sub   = pygame.font.SysFont("monospace", max( 8, int(14 * sc)))
        self._font_card  = pygame.font.SysFont("monospace", max(14, int(22 * sc)), bold=True)
        self._font_desc  = pygame.font.SysFont("monospace", max( 7, int(12 * sc)))

        self._update_card_rects()

    def _update_card_rects(self) -> None:
        """Recompute visible card rects based on current scroll offset."""
        self._card_rects = []
        for slot in range(self._n_vis):
            x = self._margin + slot * (self._card_w + self._card_gap)
            self._card_rects.append(
                pygame.Rect(x, self._card_y, self._card_w, self._card_h)
            )

    def _toggle_fullscreen(self) -> None:
        self._is_fullscreen = not self._is_fullscreen
        if self._is_fullscreen:
            new_screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        else:
            new_screen = pygame.display.set_mode((800, 600))
        self._init_layout(new_screen)

    # ── Scrolling helpers ─────────────────────────────────────────────────────

    def _clamp_scroll(self) -> None:
        max_scroll = max(0, len(self._games) - self._n_vis)
        self._scroll_offset = max(0, min(self._scroll_offset, max_scroll))

    def _ensure_selected_visible(self) -> None:
        """Scroll so that the selected card is in the viewport."""
        if self._selected_idx < self._scroll_offset:
            self._scroll_offset = self._selected_idx
        elif self._selected_idx >= self._scroll_offset + self._n_vis:
            self._scroll_offset = self._selected_idx - self._n_vis + 1
        self._clamp_scroll()

    # ── Public entry point ─────────────────────────────────────────────────────

    def run(self, gesture_src) -> str:
        pygame.mouse.set_visible(True)
        while True:
            dt = self._clock.tick(FPS) / 1000.0
            self._glow_phase = (self._glow_phase + dt * 2.5) % (2 * math.pi)
            self._nav_cd = max(0.0, self._nav_cd - dt)

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit()
                    sys.exit(0)
                result = self._handle_event(event)
                if result:
                    return result

            self._update_hover()
            result = self._handle_gesture(gesture_src, dt)
            if result:
                return result

            self._draw()
            if self._debug and gesture_src is not None:
                gs = gesture_src.get_state()
                draw_gesture_debug_overlay(
                    self._screen, gs, self._W, self._H, self._sc, self._font_card)
            pygame.display.flip()

    # ── Input handling ────────────────────────────────────────────────────────

    def _handle_event(self, event: pygame.event.Event) -> Optional[str]:
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_LEFT:
                self._navigate(-1)
            elif event.key == pygame.K_RIGHT:
                self._navigate(1)
            elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
                return self._games[self._selected_idx]
            elif event.key == pygame.K_m:
                self._cycle_mode()
            elif event.key == pygame.K_d:
                self._debug = not self._debug
            elif event.key == pygame.K_f:
                self._toggle_fullscreen()
            elif event.key == pygame.K_ESCAPE:
                pygame.quit()
                sys.exit(0)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._hover_idx is not None:
                global_idx = self._scroll_offset + self._hover_idx
                return self._games[global_idx]
        return None

    def _update_hover(self) -> None:
        mx, my = pygame.mouse.get_pos()
        self._hover_idx = None
        for slot, rect in enumerate(self._card_rects):
            global_idx = self._scroll_offset + slot
            if global_idx >= len(self._games):
                break
            if rect.collidepoint(mx, my):
                self._hover_idx = slot
                self._selected_idx = global_idx
                break

    def _handle_gesture(self, gesture_src, dt: float) -> Optional[str]:
        if gesture_src is None:
            return None
        gs = gesture_src.get_state()
        if not gs.calibrated:
            return None

        if gs.launch:
            return self._games[self._selected_idx]

        direction = 0
        if gs.paddle_velocity < -TILT_THRESHOLD:
            direction = -1
        elif gs.paddle_velocity > TILT_THRESHOLD:
            direction = 1

        if self.mode == "accessible":
            if direction != 0 and self._nav_cd <= 0:
                if direction == self._acc_hold_dir:
                    self._acc_hold += dt
                    if self._acc_hold >= ACC_HOLD_REQUIRED:
                        self._navigate(direction)
                        self._nav_cd    = ACC_NAV_CD
                        self._acc_hold  = 0.0
                else:
                    self._acc_hold_dir = direction
                    self._acc_hold     = 0.0
            elif direction == 0:
                self._acc_hold_dir = 0
                self._acc_hold     = 0.0
        else:
            if direction != 0 and direction != self._tilt_dir and self._nav_cd <= 0:
                self._navigate(direction)
                self._nav_cd = TILT_NAV_CD

        self._tilt_dir = direction
        return None

    def _navigate(self, direction: int) -> None:
        self._selected_idx = (self._selected_idx + direction) % len(self._games)
        self._ensure_selected_visible()

    def _cycle_mode(self) -> None:
        if self.mode == "keyboard":
            return
        self.mode = "accessible" if self.mode == "standard" else "standard"
        self._games = self._compute_games()
        self._selected_idx = min(self._selected_idx, len(self._games) - 1)
        self._ensure_selected_visible()
        self._init_layout(self._screen)

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _draw(self) -> None:
        self._screen.fill(BG)
        self._draw_title()
        self._draw_scroll_indicators()
        for slot in range(self._n_vis):
            global_idx = self._scroll_offset + slot
            if global_idx < len(self._games):
                self._draw_card(slot, global_idx, self._games[global_idx])
        self._draw_dots()
        self._draw_hint()

    def _draw_title(self) -> None:
        sc = self._sc
        cx = self._W // 2
        title = self._font_title.render("SELECT YOUR GAME", True, TEXT_CLR)
        self._screen.blit(title, title.get_rect(center=(cx, int(52 * sc))))

        if self._username:
            user_surf = self._font_sub.render(f"Player: {self._username}", True, (150, 200, 150))
            self._screen.blit(user_surf, user_surf.get_rect(center=(cx, int(76 * sc))))

        sub = self._font_sub.render(
            "tilt or arrow keys to choose   •   flick / enter / click to play",
            True, DIM_CLR
        )
        self._screen.blit(sub, sub.get_rect(center=(cx, int(96 * sc))))
        self._draw_mode_badge()

    def _draw_mode_badge(self) -> None:
        sc    = self._sc
        meta  = MODE_META[self.mode]
        color = meta["color"]
        label = f"MODE: {meta['label']}"
        if self.mode != "keyboard":
            label += "   (M = switch)"
        surf = self._font_sub.render(label, True, color)
        rect = surf.get_rect(center=(self._W // 2, int(114 * sc)))
        pad  = pygame.Rect(rect.left - int(8 * sc), rect.top - max(2, int(3 * sc)),
                           rect.width + int(16 * sc), rect.height + max(4, int(6 * sc)))
        bg   = pygame.Surface((pad.width, pad.height), pygame.SRCALPHA)
        bg.fill((*color, 35))
        self._screen.blit(bg, pad.topleft)
        pygame.draw.rect(self._screen, (*color, 120), pad, 1, border_radius=max(4, int(8 * sc)))
        self._screen.blit(surf, rect)

    def _draw_scroll_indicators(self) -> None:
        """Draw left/right arrow indicators when more cards exist off-screen."""
        sc = self._sc
        cy = self._card_y + self._card_h // 2
        arrow_size = max(10, int(18 * sc))
        arrow_pad  = max(4,  int(8  * sc))
        color = (180, 180, 200)

        # Left arrow
        if self._scroll_offset > 0:
            x = self._margin - arrow_pad - arrow_size
            pts = [
                (x + arrow_size, cy - arrow_size // 2),
                (x,              cy),
                (x + arrow_size, cy + arrow_size // 2),
            ]
            pygame.draw.polygon(self._screen, color, pts)

        # Right arrow
        if self._scroll_offset + self._n_vis < len(self._games):
            x = self._margin + self._n_vis * (self._card_w + self._card_gap) - self._card_gap + arrow_pad
            pts = [
                (x,              cy - arrow_size // 2),
                (x + arrow_size, cy),
                (x,              cy + arrow_size // 2),
            ]
            pygame.draw.polygon(self._screen, color, pts)

    def _draw_dots(self) -> None:
        """Draw pagination dots below the cards."""
        if len(self._games) <= self._n_vis:
            return
        sc  = self._sc
        r   = max(3, int(5 * sc))
        gap = r * 3
        total_w = len(self._games) * (r * 2 + gap) - gap
        x   = self._W // 2 - total_w // 2
        y   = self._card_y + self._card_h + max(8, int(14 * sc))
        for i in range(len(self._games)):
            is_vis = self._scroll_offset <= i < self._scroll_offset + self._n_vis
            is_sel = (i == self._selected_idx)
            if is_sel:
                clr = (200, 220, 255)
            elif is_vis:
                clr = (90, 90, 120)
            else:
                clr = (50, 50, 70)
            pygame.draw.circle(self._screen, clr, (x + r, y + r), r)
            x += r * 2 + gap

    def _draw_card(self, slot: int, global_idx: int, game_id: str) -> None:
        rect   = self._card_rects[slot]
        meta   = GAME_META[game_id]
        accent = meta["accent"]
        is_sel = (global_idx == self._selected_idx)

        pygame.draw.rect(self._screen, CARD_BG, rect, border_radius=10)

        if is_sel:
            self._draw_glow(rect, accent)
            border_clr = accent
            border_w   = 3
        else:
            border_clr = tuple(max(0, c - 120) for c in accent)  # type: ignore
            border_w   = 2

        pygame.draw.rect(self._screen, border_clr, rect, border_w, border_radius=10)

        sc = self._sc
        title_surf = self._font_card.render(meta["title"], True,
                                            accent if is_sel else DIM_CLR)
        self._screen.blit(title_surf, title_surf.get_rect(
            centerx=rect.centerx, top=rect.top + max(8, int(14 * sc))
        ))

        pad_h  = max(6, int(12 * sc))
        prev_h = int(140 * sc)
        preview_rect = pygame.Rect(
            rect.left + pad_h, rect.top + max(26, int(50 * sc)),
            rect.width - 2 * pad_h, prev_h,
        )
        self._draw_preview(game_id, preview_rect, accent, is_sel)

        desc_key = "desc_ac" if self.mode == "accessible" else "desc"
        for j, line in enumerate(meta[desc_key]):
            clr  = TEXT_CLR if is_sel else DIM_CLR
            surf = self._font_desc.render(line, True, clr)
            self._screen.blit(surf, surf.get_rect(
                centerx=rect.centerx,
                top=rect.top + int(205 * sc) + j * max(14, int(18 * sc))
            ))

    def _draw_glow(self, rect: pygame.Rect, accent: Tuple[int, int, int]) -> None:
        sc = self._sc
        for extra, alpha in ((int(14*sc), 35), (int(9*sc), 22), (int(4*sc), 12)):
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
        prev_clip = self._screen.get_clip()
        self._screen.set_clip(area)
        pygame.draw.rect(self._screen, (10, 10, 20), area, border_radius=6)
        dim = 180 if active else 100

        if game_id == "bricks":
            self._draw_bricks_preview(area, dim)
        elif game_id == "snake":
            self._draw_snake_preview(area, dim)
        elif game_id == "fruit_ninja":
            self._draw_fruit_ninja_preview(area, dim)
        elif game_id == "calibration":
            self._draw_calibration_preview(area, dim)

        self._screen.set_clip(prev_clip)

    def _draw_bricks_preview(self, area: pygame.Rect, dim: int) -> None:
        sc = self._sc
        PALETTE = [
            (220, 60, 60), (240, 160, 40), (60, 200, 100),
            (60, 140, 240), (180, 60, 220), (240, 240, 60),
        ]
        bw   = max(6,  int(26 * sc))
        bh   = max(3,  int(10 * sc))
        cols, rows = 6, 4
        pad_x = (area.width  - cols * bw) // 2
        pad_y = max(4, int(6 * sc))
        for row in range(rows):
            for col in range(cols):
                base = PALETTE[row % len(PALETTE)]
                clr  = tuple(min(255, int(c * dim / 255)) for c in base)
                bx = area.left + pad_x + col * bw + 1
                by = area.top  + pad_y + row * (bh + 2)
                pygame.draw.rect(self._screen, clr, (bx, by, max(2, bw - 2), bh), border_radius=2)

        pw = max(14, int(40 * sc))
        ph = max(2,  int(6  * sc))
        px = area.centerx - pw // 2
        py = area.bottom - max(6, int(14 * sc))
        pygame.draw.rect(self._screen, (min(255, dim), min(255, int(dim * 0.7)), 255),
                         (px, py, pw, ph), border_radius=max(2, int(3 * sc)))

        ball_r = max(2, int(4 * sc))
        bx2 = area.centerx + max(3, int(8 * sc))
        by2 = area.bottom  - max(10, int(24 * sc))
        pygame.draw.circle(self._screen, (dim, dim, dim), (bx2, by2), ball_r)

    def _draw_snake_preview(self, area: pygame.Rect, dim: int) -> None:
        sc   = self._sc
        CELL = max(5, int(10 * sc))
        for x in range(area.left, area.right, CELL):
            pygame.draw.line(self._screen, (30, 30, 50), (x, area.top), (x, area.bottom))
        for y in range(area.top, area.bottom, CELL):
            pygame.draw.line(self._screen, (30, 30, 50), (area.left, y), (area.right, y))

        snake_cells = [(8, 4), (7, 4), (6, 4), (5, 4), (4, 4), (4, 5), (4, 6)]
        ox = area.left + max(3, int(6 * sc))
        oy = area.top  + max(3, int(6 * sc))
        br = max(1, int(2 * sc))
        for i, (cx, cy) in enumerate(snake_cells):
            r = pygame.Rect(ox + cx * CELL + 1, oy + cy * CELL + 1, CELL - 2, CELL - 2)
            if i == 0:
                clr = (min(255, int(140 * dim / 255)), 255, min(255, int(140 * dim / 255)))
            else:
                clr = (min(255, int(80 * dim / 255)), min(255, int(220 * dim / 255)),
                       min(255, int(100 * dim / 255)))
            pygame.draw.rect(self._screen, clr, r, border_radius=br)

        fcx = ox + 11 * CELL + CELL // 2
        fcy = oy + 4  * CELL + CELL // 2
        alpha = dim
        clr = (min(255, int(210 * alpha / 255)), min(255, int(40 * alpha / 255)),
               min(255, int(40 * alpha / 255)))
        ar = max(2, int(4 * sc))
        pygame.draw.circle(self._screen, clr, (fcx, fcy + 1), ar)

    def _draw_fruit_ninja_preview(self, area: pygame.Rect, dim: int) -> None:
        import math
        sc = self._sc
        fruits = [
            (0.22, 0.55, (215, 50, 50),  (160, 25, 25), 0.13),
            (0.50, 0.38, (60, 175, 60),  (210, 55, 55), 0.17),
            (0.78, 0.52, (240, 150, 30), (200,110, 20), 0.13),
            (0.38, 0.70, (210, 55, 85),  (255,190,180), 0.10),
            (0.65, 0.65, (245, 220, 55), (200,165, 25), 0.12),
        ]
        fade = dim / 255.0
        for fx, fy, clr, inner_clr, r_frac in fruits:
            cx  = int(area.left + fx * area.width)
            cy  = int(area.top  + fy * area.height)
            r   = max(3, int(r_frac * min(area.width, area.height)))
            c   = tuple(min(255, int(v * fade)) for v in clr)
            ic  = tuple(min(255, int(v * fade)) for v in inner_clr)
            pygame.draw.circle(self._screen, c,  (cx, cy), r)
            pygame.draw.circle(self._screen, ic, (cx, cy), max(2, r // 2))
            hl  = tuple(min(255, int((v + 80) * fade)) for v in clr)
            pygame.draw.circle(self._screen, hl, (cx - r // 3, cy - r // 3), max(1, r // 3))

        trail_alpha = int(170 * fade)
        trail_clr   = (min(255, trail_alpha + 20), min(255, trail_alpha), 255)
        x0 = area.left + int(area.width  * 0.15)
        y0 = area.top  + int(area.height * 0.75)
        x1 = area.left + int(area.width  * 0.88)
        y1 = area.top  + int(area.height * 0.22)
        lw = max(1, int(2 * sc))
        pygame.draw.line(self._screen, trail_clr, (x0, y0), (x1, y1), lw)
        for t in (0.3, 0.55, 0.80):
            tx = int(x0 + (x1 - x0) * t)
            ty = int(y0 + (y1 - y0) * t)
            pygame.draw.circle(self._screen, trail_clr, (tx, ty), max(2, int(3 * sc)))

    def _draw_calibration_preview(self, area: pygame.Rect, dim: int) -> None:
        import math
        sc  = self._sc
        cx  = area.centerx
        cy  = area.centery
        r   = min(area.width, area.height) // 2 - max(2, int(3 * sc))

        circle_clr = tuple(min(255, int(c * dim / 255)) for c in (40, 80, 120))
        pygame.draw.circle(self._screen, circle_clr, (cx, cy), r)

        tick_clr = tuple(min(255, int(c * dim / 255)) for c in (140, 170, 200))
        for i in range(0, 360, 30):
            angle    = math.radians(i - 90)
            major    = (i % 90 == 0)
            tick_len = r * (0.20 if major else 0.10)
            x1 = cx + (r - tick_len) * math.cos(angle)
            y1 = cy + (r - tick_len) * math.sin(angle)
            x2 = cx + r * math.cos(angle)
            y2 = cy + r * math.sin(angle)
            pygame.draw.line(self._screen, tick_clr,
                             (int(x1), int(y1)), (int(x2), int(y2)), 1)

        lbl_r    = r - max(5, int(10 * sc))
        card_clr = tuple(min(255, int(c * dim / 255)) for c in (255, 210, 50))
        for label, deg in [("N", 0), ("E", 90), ("S", 180), ("W", 270)]:
            angle = math.radians(deg - 90)
            lx = cx + lbl_r * math.cos(angle)
            ly = cy + lbl_r * math.sin(angle)
            surf = self._font_desc.render(label, True, card_clr)
            self._screen.blit(surf, surf.get_rect(center=(int(lx), int(ly))))

        plane_sc  = r / 55.0
        plane_clr = tuple(min(255, int(c * dim / 255)) for c in (220, 230, 240))

        def _rot(x, y, angle_rad=0.0):
            cos_a, sin_a = math.cos(angle_rad), math.sin(angle_rad)
            return (int(cx + x * cos_a - y * sin_a),
                    int(cy + x * sin_a + y * cos_a))

        fuse = [
            _rot(0,           -28 * plane_sc),
            _rot(4  * plane_sc, -14 * plane_sc),
            _rot(5  * plane_sc,  10 * plane_sc),
            _rot(0,            24 * plane_sc),
            _rot(-5 * plane_sc,  10 * plane_sc),
            _rot(-4 * plane_sc, -14 * plane_sc),
        ]
        pygame.draw.polygon(self._screen, plane_clr, fuse)
        for side in (-1, 1):
            wing = [
                _rot(side * 4  * plane_sc,  -5 * plane_sc),
                _rot(side * 28 * plane_sc,   3 * plane_sc),
                _rot(side * 23 * plane_sc,   8 * plane_sc),
                _rot(side * 3  * plane_sc,   1 * plane_sc),
            ]
            pygame.draw.polygon(self._screen, plane_clr, wing)
        pygame.draw.circle(self._screen, plane_clr, _rot(0, 0), max(2, int(3 * plane_sc)))

    def _draw_hint(self) -> None:
        sc = self._sc
        controls = [
            ("Sensor", "tilt to choose • flick to play"),
            ("Mouse",  "hover to choose • click to play"),
            ("Keys",   "← → to choose • Enter to play  •  F = fullscreen"),
            ("In-game", "L = Learn  •  T = Test  •  R = Regular mode"),
        ]
        y = self._card_y + self._card_h + max(18, int(30 * sc))
        for label, text in controls:
            line = f"{label}: {text}"
            clr  = (100, 180, 100) if label == "In-game" else DIM_CLR
            surf = self._font_sub.render(line, True, clr)
            self._screen.blit(surf, surf.get_rect(center=(self._W // 2, y)))
            y += max(12, int(17 * sc))
