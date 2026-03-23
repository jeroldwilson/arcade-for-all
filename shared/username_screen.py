"""
shared/username_screen.py — Username prompt and profile selection screen

Shows at startup. Lets the player:
  • Pick an existing profile from the list
  • Type a new username
  • Press ENTER to confirm

Returns the selected username string.
"""

import json
import sys
from pathlib import Path
from typing import List, Optional

import pygame

PROFILES_DIR = Path(__file__).parent.parent / "data" / "profiles"

BG       = (15,  15,  25)
TEXT_CLR = (255, 255, 255)
DIM_CLR  = (165, 165, 180)
ACCENT   = (110, 200, 255)
SEL_BG   = (30,  60, 100)
CARD_BG  = (30,  30,  52)

MAX_NAME_LEN = 20


def _load_profiles() -> List[str]:
    """Return sorted list of existing usernames."""
    if not PROFILES_DIR.exists():
        return []
    names = []
    for p in PROFILES_DIR.glob("*.json"):
        try:
            data = json.loads(p.read_text())
            names.append(data.get("username", p.stem))
        except Exception:
            names.append(p.stem)
    return sorted(names)


def save_profile(username: str) -> None:
    """Create or touch a profile file for the given username."""
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    path = PROFILES_DIR / f"{username}.json"
    if not path.exists():
        import time
        path.write_text(json.dumps({"username": username, "created": time.strftime("%Y-%m-%d %H:%M:%S")}))


class UsernameScreen:
    """
    Blocking screen that asks the player to enter or select a username.
    Returns the chosen username string.
    """

    def __init__(self, screen: pygame.Surface, clock: pygame.time.Clock):
        self._screen = screen
        self._clock  = clock
        self._W, self._H = screen.get_size()
        sc = min(self._W / 800, self._H / 600)
        self._sc = sc

        self._font_title = pygame.font.SysFont("monospace", max(22, int(40 * sc)), bold=True)
        self._font_lg    = pygame.font.SysFont("monospace", max(16, int(28 * sc)), bold=True)
        self._font_md    = pygame.font.SysFont("monospace", max(12, int(20 * sc)))
        self._font_sm    = pygame.font.SysFont("monospace", max( 9, int(14 * sc)))

        self._profiles    = _load_profiles()
        self._selected    = -1              # -1 = "New profile" entry
        self._text_input  = ""             # typed characters
        self._cursor_vis  = True
        self._cursor_tick = 0.0
        self._error_msg   = ""

    def run(self) -> str:
        """Block until a valid username is confirmed. Returns the username."""
        pygame.mouse.set_visible(True)
        while True:
            dt = self._clock.tick(60) / 1000.0
            self._cursor_tick += dt
            if self._cursor_tick >= 0.5:
                self._cursor_tick = 0.0
                self._cursor_vis  = not self._cursor_vis

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit()
                    sys.exit(0)
                result = self._handle_event(event)
                if result:
                    save_profile(result)
                    return result

            self._draw()
            pygame.display.flip()

    def _handle_event(self, event: pygame.event.Event) -> Optional[str]:
        if event.type == pygame.KEYDOWN:
            return self._on_key(event)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            return self._on_click(pygame.mouse.get_pos())
        return None

    def _on_key(self, event: pygame.event.Event) -> Optional[str]:
        key = event.key

        if key == pygame.K_RETURN:
            return self._confirm()

        elif key == pygame.K_ESCAPE:
            # Allow skipping with ESC — use "Guest"
            return "Guest"

        elif key == pygame.K_UP:
            # Navigate existing profiles (or to new)
            if self._profiles:
                if self._selected == -1:
                    self._selected = len(self._profiles) - 1
                else:
                    self._selected = (self._selected - 1) % len(self._profiles)
                    if self._selected == len(self._profiles) - 1:
                        self._selected = -1  # wrap back to new

        elif key == pygame.K_DOWN:
            if self._profiles:
                if self._selected == -1:
                    self._selected = 0
                else:
                    self._selected = (self._selected + 1) % len(self._profiles)

        elif key == pygame.K_BACKSPACE:
            if self._selected == -1:
                self._text_input = self._text_input[:-1]

        elif key == pygame.K_TAB:
            # Toggle between new-profile input and existing list
            self._selected = 0 if (self._selected == -1 and self._profiles) else -1

        else:
            # Type characters for new username
            if self._selected == -1:
                ch = event.unicode
                if ch.isprintable() and ch not in ("/", "\\", ".", " ") and len(self._text_input) < MAX_NAME_LEN:
                    self._text_input += ch
                    self._error_msg = ""

        return None

    def _on_click(self, pos) -> Optional[str]:
        mx, my = pos
        # Check existing profile rows
        for i, rect in enumerate(self._profile_rects):
            if rect.collidepoint(mx, my):
                if self._selected == i:
                    return self._confirm()   # double-click to confirm
                self._selected = i
                return None
        # Check "New profile" area
        if hasattr(self, "_new_rect") and self._new_rect.collidepoint(mx, my):
            self._selected = -1
        return None

    def _confirm(self) -> Optional[str]:
        if self._selected >= 0 and self._selected < len(self._profiles):
            return self._profiles[self._selected]
        # New username from text input
        name = self._text_input.strip()
        if not name:
            self._error_msg = "Please type a name first"
            return None
        if len(name) < 2:
            self._error_msg = "Name must be at least 2 characters"
            return None
        return name

    def _draw(self) -> None:
        sc = self._sc
        W, H = self._W, self._H
        self._screen.fill(BG)

        cx = W // 2
        y  = int(40 * sc)

        # Title
        t = self._font_title.render("WHO ARE YOU?", True, ACCENT)
        self._screen.blit(t, t.get_rect(center=(cx, y)))
        y += int(50 * sc)

        sub = self._font_sm.render("Your name links your gesture training data across sessions.", True, DIM_CLR)
        self._screen.blit(sub, sub.get_rect(center=(cx, y)))
        y += int(36 * sc)

        self._profile_rects = []

        if self._profiles:
            lbl = self._font_sm.render("── Existing profiles ──", True, DIM_CLR)
            self._screen.blit(lbl, lbl.get_rect(center=(cx, y)))
            y += int(28 * sc)

            row_h  = max(32, int(44 * sc))
            box_w  = min(int(400 * sc), W - int(80 * sc))
            box_x  = cx - box_w // 2

            for i, name in enumerate(self._profiles):
                rect = pygame.Rect(box_x, y, box_w, row_h)
                self._profile_rects.append(rect)

                is_sel = (i == self._selected)
                bg_clr = SEL_BG if is_sel else CARD_BG
                pygame.draw.rect(self._screen, bg_clr, rect, border_radius=6)
                border_clr = ACCENT if is_sel else (60, 60, 90)
                pygame.draw.rect(self._screen, border_clr, rect, 1 if not is_sel else 2, border_radius=6)

                name_surf = self._font_md.render(name, True, TEXT_CLR if is_sel else DIM_CLR)
                self._screen.blit(name_surf, name_surf.get_rect(
                    midleft=(box_x + max(10, int(16 * sc)), rect.centery)))

                if is_sel:
                    hint = self._font_sm.render("ENTER to play", True, ACCENT)
                    self._screen.blit(hint, hint.get_rect(
                        midright=(box_x + box_w - max(8, int(12 * sc)), rect.centery)))

                y += row_h + max(4, int(6 * sc))

            y += int(16 * sc)

        # New profile section
        box_w = min(int(400 * sc), W - int(80 * sc))
        box_x = cx - box_w // 2
        new_lbl = self._font_sm.render("── New profile ──", True, DIM_CLR)
        self._screen.blit(new_lbl, new_lbl.get_rect(center=(cx, y)))
        y += int(28 * sc)

        input_h = max(34, int(48 * sc))
        input_rect = pygame.Rect(box_x, y, box_w, input_h)
        self._new_rect = input_rect

        is_new_sel = (self._selected == -1)
        bg_clr = SEL_BG if is_new_sel else CARD_BG
        pygame.draw.rect(self._screen, bg_clr, input_rect, border_radius=6)
        border_clr = ACCENT if is_new_sel else (60, 60, 90)
        pygame.draw.rect(self._screen, border_clr, input_rect,
                         2 if is_new_sel else 1, border_radius=6)

        display_text = self._text_input
        if is_new_sel and self._cursor_vis:
            display_text += "|"
        elif not display_text:
            display_text = "type your name…"

        text_clr = TEXT_CLR if (self._text_input or is_new_sel) else (80, 80, 110)
        ts = self._font_md.render(display_text, True, text_clr)
        self._screen.blit(ts, ts.get_rect(
            midleft=(box_x + max(10, int(16 * sc)), input_rect.centery)))

        y += input_h + max(6, int(10 * sc))

        # Error message
        if self._error_msg:
            err = self._font_sm.render(self._error_msg, True, (255, 100, 100))
            self._screen.blit(err, err.get_rect(center=(cx, y)))
            y += int(24 * sc)

        # Controls hint
        y = H - max(50, int(70 * sc))
        hints = [
            "↑ ↓  navigate existing profiles",
            "Type  create new profile",
            "ENTER  confirm   •   ESC  skip (Guest)",
        ]
        for hint in hints:
            s = self._font_sm.render(hint, True, DIM_CLR)
            self._screen.blit(s, s.get_rect(center=(cx, y)))
            y += max(14, int(20 * sc))
