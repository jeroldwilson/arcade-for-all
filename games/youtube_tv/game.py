"""
games/youtube_tv/game.py — Accessible Wrist-Gesture YouTube TV Hub

Launched directly from the Pygame HomeScreen ("YOUTUBE TV" card) or via
`youtube_bridge.py`.

Features:
  • 10-Foot HDMI TV Interface inside Pygame AND synced Fullscreen Web Player Deck
  • Deliberate 3-Step Combo Gesture Lock (`YouTubeGestureController`) so excited
    hand movements while watching never accidentally skip a video:
      - Step 1: Flick Wrist UP (or Hold Tilt 0.9s) to Unlock Remote
      - Step 2: Relax Wrist to Center Neutral
      - Step 3: Swipe or Hold Left / Right within 6 seconds to change video
  • Browser-to-Pygame ESC Bridge (`/api/quit`) so pressing ESC or clicking
    "Back to Arcade" inside Chrome/Safari immediately returns to the Pygame
    Home Screen and focuses the Arcade window.
"""

import math
import webbrowser
from typing import Optional, Tuple

import pygame

from shared.gesture import CONFIG_ACCESSIBLE_FLICK_STEER, CONFIG_STANDARD
from shared.gesture_hud import GestureHUD
from shared.learn_test_support import draw_gesture_debug_overlay
from shared.game_experience import NebulaBg, StarField
from shared.youtube_control import YouTubeDeckServer, YouTubeGestureController


# ── Color Palette ─────────────────────────────────────────────────────────────
BG_DARK      = (10, 14, 28)
CARD_BG      = (20, 28, 52)
NEON_CYAN    = (0, 235, 255)
NEON_GREEN   = (60, 255, 130)
NEON_MAGENTA = (255, 55, 165)
NEON_ORANGE  = (255, 155, 45)
NEON_YELLOW  = (255, 230, 65)
TEXT_WHITE   = (255, 255, 255)
TEXT_DIM     = (165, 180, 210)


def _hex_to_rgb(hex_str: str, fallback: Tuple[int, int, int] = NEON_CYAN) -> Tuple[int, int, int]:
    s = (hex_str or "").strip().lstrip("#")
    if len(s) == 6:
        try:
            return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
        except ValueError:
            pass
    return fallback


class YouTubeTVGame:
    """
    Accessible YouTube TV Channel Surf & Remote Hub inside the Pygame Arcade.
    Automatically starts `YouTubeDeckServer` and opens the TV Web Deck while
    providing a full visual remote + channel surfer inside Pygame.
    """

    def __init__(
        self,
        screen: pygame.Surface,
        clock: pygame.time.Clock,
        debug: bool = False,
        mode: str = "accessible",
        audio=None,
        username: str = "",
        open_browser_on_start: bool = True,
        native_browser: bool = False,
        browser_submode: str = "playlist",
    ):
        self._screen = screen
        self._clock = clock
        self._debug = debug
        self.mode = mode
        self._audio = audio
        self._username = username or "Guest"
        self._open_browser_on_start = open_browser_on_start

        self.controller = YouTubeGestureController(
            username=self._username,
            mode=mode,
            native_browser=native_browser,
            browser_submode=browser_submode,
        )
        self.server = YouTubeDeckServer(self.controller)

        self.hud = GestureHUD(
            "/Users/jerold/.gemini/antigravity-ide/brain/3c53c120-8bf4-4a05-a904-340edfef9b68/metamotion_kid_hand_flat_1788027714986.jpg",
            scale=0.28,
        )

        self._nebula = NebulaBg()
        self._stars = StarField(80)
        self._banner_text: str = ""
        self._banner_timer: float = 0.0
        self._pulse: float = 0.0
        self._prev_combo_step: int = 0

        self._init_layout(screen)

    def _init_layout(self, screen: pygame.Surface) -> None:
        self._screen = screen
        sw, sh = screen.get_size()
        self._W, self._H = sw, sh
        self._is_fullscreen = not (sw == 800 and sh == 600)
        sc = min(sw / 800.0, sh / 600.0)
        self._sc = sc

        self._font_xl = self._make_font(max(22, int(34 * sc)), bold=True)
        self._font_lg = self._make_font(max(16, int(24 * sc)), bold=True)
        self._font_md = self._make_font(max(12, int(17 * sc)), bold=True)
        self._font_sm = self._make_font(max(10, int(13 * sc)), bold=False)

        # Clickable UI buttons (4 buttons across top)
        btn_w = int(172 * sc)
        btn_h = int(38 * sc)
        btn_y = int(112 * sc)
        gap = int(10 * sc)
        total_w = btn_w * 4 + gap * 3
        start_x = (sw - total_w) // 2

        self._btn_back_home = pygame.Rect(start_x, btn_y, btn_w, btn_h)
        self._btn_open_tv   = pygame.Rect(start_x + (btn_w + gap), btn_y, btn_w, btn_h)
        self._btn_next_ch   = pygame.Rect(start_x + (btn_w + gap) * 2, btn_y, btn_w, btn_h)
        self._btn_refresh   = pygame.Rect(start_x + (btn_w + gap) * 3, btn_y, btn_w, btn_h)

        # Bottom Left / Right swipe wing rects
        wing_w = int(220 * sc)
        wing_h = int(84 * sc)
        wing_y = sh - wing_h - int(22 * sc)
        self._left_wing_rect = pygame.Rect(int(24 * sc), wing_y, wing_w, wing_h)
        self._right_wing_rect = pygame.Rect(sw - wing_w - int(24 * sc), wing_y, wing_w, wing_h)

    @staticmethod
    def _make_font(size: int, bold: bool = False) -> pygame.font.Font:
        try:
            return pygame.font.SysFont("Arial", size, bold=bold)
        except Exception:
            return pygame.font.Font(None, max(12, int(size * 1.15)))

    def _toggle_fullscreen(self) -> None:
        self._is_fullscreen = not self._is_fullscreen
        if self._is_fullscreen:
            new_screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        else:
            new_screen = pygame.display.set_mode((800, 600))
        self._init_layout(new_screen)

    def _show_banner(self, text: str) -> None:
        self._banner_text = text
        self._banner_timer = 2.0

    # ── Main Game Loop ────────────────────────────────────────────────────────

    def run(self, gesture_src) -> str:
        if hasattr(gesture_src, "config"):
            gesture_src.config = (
                CONFIG_ACCESSIBLE_FLICK_STEER if self.mode == "accessible" else CONFIG_STANDARD
            )

        deck_url = self.server.start(open_browser=self._open_browser_on_start)
        self.controller.tts.speak(
            f"YouTube T V ready for {self._username}. Flick wrist up to unlock remote, then swipe left or right."
        )
        self._show_banner("STEP 1: FLICK UP (OR HOLD 1s) TO UNLOCK REMOTE")

        try:
            while True:
                dt = self._clock.tick(60) / 1000.0
                self._pulse = (self._pulse + dt * 3.0) % (2 * math.pi)
                if self._banner_timer > 0.0:
                    self._banner_timer = max(0.0, self._banner_timer - dt)

                # Check if user pressed ESC or "Back to Arcade" inside the browser tab!
                if self.controller.quit_requested:
                    return "home"

                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        return "quit"
                    res = self._handle_event(event, deck_url)
                    if res:
                        return res

                gs = gesture_src.get_state() if gesture_src is not None else None
                action = self.controller.update(gs, dt)

                # Notify on combo unlock transition
                if self.controller.combo_step > 0 and self._prev_combo_step == 0:
                    if hasattr(gesture_src, "vibrate"):
                        gesture_src.vibrate(0.08)
                    self._show_banner("🔓 REMOTE UNLOCKED — SWIPE LEFT OR RIGHT!")
                self._prev_combo_step = self.controller.combo_step

                if action:
                    self._on_action_triggered(action, gesture_src)

                self._nebula.update(dt)
                self._stars.update(dt)
                self._draw(gs, deck_url)

                if self._debug and gs is not None:
                    draw_gesture_debug_overlay(
                        self._screen, gs, self._W, self._H, self._sc, self._font_md
                    )
                if gs is not None:
                    self.hud.draw(self._screen, gs, self._W - 95, self._H - 190)

                pygame.display.flip()
        finally:
            self.server.stop()

    def _on_action_triggered(self, action: str, gesture_src) -> None:
        if hasattr(gesture_src, "vibrate"):
            gesture_src.vibrate(0.14)
        if self._audio is not None and hasattr(self._audio, "play_paddle_hit"):
            try:
                self._audio.play_paddle_hit()
            except Exception:
                pass

        item = self.controller.current_item
        ch = self.controller.current_channel
        if action == "next":
            self._show_banner(f"NEXT ▶  {item.get('title', '')[:32]}")
        elif action == "prev":
            self._show_banner(f"◀ PREV  {item.get('title', '')[:32]}")
        elif action in ("next_channel", "prev_channel"):
            self._show_banner(f"📺 {ch.get('name', 'Channel')}")
        elif action == "toggle_pause":
            self._show_banner("⏯ PLAY / PAUSE")

    def _handle_event(self, event: pygame.event.Event, deck_url: str) -> Optional[str]:
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_ESCAPE, pygame.K_BACKSPACE, pygame.K_q):
                return "home"
            elif event.key == pygame.K_RIGHT:
                act = self.controller.trigger_action("next")
                self._on_action_triggered(act, None)
            elif event.key == pygame.K_LEFT:
                act = self.controller.trigger_action("prev")
                self._on_action_triggered(act, None)
            elif event.key in (pygame.K_UP, pygame.K_c):
                act = self.controller.trigger_action("next_channel")
                self._on_action_triggered(act, None)
            elif event.key == pygame.K_DOWN:
                act = self.controller.trigger_action("prev_channel")
                self._on_action_triggered(act, None)
            elif event.key == pygame.K_u:
                self.controller.trigger_action("unlock")
                self._show_banner("🔓 REMOTE UNLOCKED — SWIPE LEFT OR RIGHT!")
            elif event.key == pygame.K_SPACE:
                act = self.controller.trigger_action("toggle_pause")
                self._on_action_triggered(act, None)
            elif event.key == pygame.K_r:
                self.controller.refresh_default_channels()
                self._show_banner("REFRESHED CHANNELS & MUSIC LINKS!")
            elif event.key == pygame.K_b:
                webbrowser.open(deck_url)
                self._show_banner("OPENED TV WEB PLAYER IN BROWSER")
            elif event.key == pygame.K_n:
                self.controller.native_browser = not self.controller.native_browser
                state_str = "ON (Chrome/Safari Hotkeys)" if self.controller.native_browser else "OFF (TV Web Deck)"
                self._show_banner(f"NATIVE BROWSER MODE: {state_str}")
            elif event.key == pygame.K_d:
                self._debug = not self._debug
            elif event.key == pygame.K_f:
                self._toggle_fullscreen()

        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            pos = event.pos
            if self._btn_back_home.collidepoint(pos):
                return "home"
            elif self._btn_open_tv.collidepoint(pos):
                webbrowser.open(deck_url)
                self._show_banner("OPENED TV WEB PLAYER")
            elif self._btn_next_ch.collidepoint(pos):
                act = self.controller.trigger_action("next_channel")
                self._on_action_triggered(act, None)
            elif self._btn_refresh.collidepoint(pos):
                self.controller.refresh_default_channels()
                self._show_banner("REFRESHED DEFAULT CHANNELS!")
            elif self._left_wing_rect.collidepoint(pos):
                act = self.controller.trigger_action("prev")
                self._on_action_triggered(act, None)
            elif self._right_wing_rect.collidepoint(pos):
                act = self.controller.trigger_action("next")
                self._on_action_triggered(act, None)
        return None

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _draw(self, gs, deck_url: str) -> None:
        sc = self._sc
        self._nebula.draw(self._screen)
        self._stars.draw(self._screen)

        cx = self._W // 2
        snap = self.controller.get_snapshot()
        accent = _hex_to_rgb(snap.get("channel_accent", "#00E5FF"))

        # 1. Top Title & Player Status
        title = self._font_xl.render("ASTRA YOUTUBE TV CONTROLLER", True, TEXT_WHITE)
        self._screen.blit(title, title.get_rect(center=(cx, int(36 * sc))))

        sub_txt = (
            f"PLAYER: {self._username}   •   3-Step Anti-Spasm Combo Active   •   ESC = Back to Arcade"
        )
        sub = self._font_sm.render(sub_txt, True, NEON_CYAN)
        self._screen.blit(sub, sub.get_rect(center=(cx, int(68 * sc))))

        hint = self._font_sm.render(
            "Step 1: Flick Wrist UP (or Hold 1s) to Unlock  →  Step 2: Center Wrist  →  Step 3: Swipe Left/Right",
            True,
            NEON_YELLOW,
        )
        self._screen.blit(hint, hint.get_rect(center=(cx, int(90 * sc))))

        # 2. Top Action Buttons
        self._draw_button(self._btn_back_home, "⬅ Back to Arcade (ESC)", NEON_ORANGE)
        self._draw_button(self._btn_open_tv, "Open TV Player (B)", NEON_CYAN)
        self._draw_button(self._btn_next_ch, "Switch Channel (C)", NEON_GREEN)
        self._draw_button(self._btn_refresh, "Refresh Links (R)", NEON_MAGENTA)

        # 3. Center Active Channel & Video Stage Card
        stage_w = int(680 * sc)
        stage_h = int(260 * sc)
        stage_rect = pygame.Rect(cx - stage_w // 2, int(166 * sc), stage_w, stage_h)

        pygame.draw.rect(self._screen, CARD_BG, stage_rect, border_radius=int(16 * sc))
        pygame.draw.rect(self._screen, accent, stage_rect, max(2, int(3 * sc)), border_radius=int(16 * sc))

        # Channel header inside card
        ch_name = snap.get("channel_name", "Channel 1")
        ch_surf = self._font_lg.render(f"📺  {ch_name}", True, accent)
        self._screen.blit(ch_surf, ch_surf.get_rect(center=(cx, stage_rect.top + int(36 * sc))))

        # Current video box
        cur_item = snap.get("current_item", {})
        vid_title = cur_item.get("title", "No video selected")
        vid_surf = self._font_xl.render(vid_title[:38], True, TEXT_WHITE)
        self._screen.blit(vid_surf, vid_surf.get_rect(center=(cx, stage_rect.top + int(92 * sc))))

        # 3-Step Combo Status Badge inside Stage Card
        step = snap.get("combo_step", 0)
        if step == 0:
            step_str = "🔒 STEP 1: FLICK WRIST UP (OR HOLD 1s) TO UNLOCK REMOTE (Excited hand moves ignored)"
            step_col = NEON_ORANGE
        elif step == 1:
            step_str = "⏳ STEP 2: RELAX WRIST BACK TO CENTER NEUTRAL..."
            step_col = NEON_YELLOW
        else:
            step_str = f"🔓 STEP 3: REMOTE ARMED ({snap.get('combo_timer', 0.0):.1f}s) — SWIPE OR HOLD LEFT / RIGHT NOW!"
            step_col = NEON_GREEN

        st_surf = self._font_md.render(step_str, True, step_col)
        self._screen.blit(st_surf, st_surf.get_rect(center=(cx, stage_rect.top + int(144 * sc))))

        # Mini preview of Previous / Next video titles
        channels = snap.get("channels", [])
        cur_ch = channels[snap["channel_idx"] % len(channels)] if channels else {"items": []}
        items = cur_ch.get("items", [])
        if len(items) > 1:
            prev_it = items[(snap["item_idx"] - 1) % len(items)]
            next_it = items[(snap["item_idx"] + 1) % len(items)]
            p_surf = self._font_sm.render(f"◀ Prev: {prev_it.get('title', '')[:26]}", True, NEON_CYAN)
            n_surf = self._font_sm.render(f"Next: {next_it.get('title', '')[:26]} ▶", True, NEON_GREEN)
            self._screen.blit(
                p_surf,
                p_surf.get_rect(left=stage_rect.left + int(24 * sc), bottom=stage_rect.bottom - int(48 * sc)),
            )
            self._screen.blit(
                n_surf,
                n_surf.get_rect(right=stage_rect.right - int(24 * sc), bottom=stage_rect.bottom - int(48 * sc)),
            )

        cfg_txt = (
            f"Press ESC in Browser or Here to Exit   •   Press R to Refresh Music Links"
        )
        cfg_surf = self._font_sm.render(cfg_txt, True, TEXT_DIM)
        self._screen.blit(cfg_surf, cfg_surf.get_rect(center=(cx, stage_rect.bottom - int(18 * sc))))

        # 4. Bottom 10-Foot Gesture HUD
        self._draw_bottom_gesture_hud(snap)

        # 5. Toast Banner on Swipe
        if self._banner_timer > 0.0 and self._banner_text:
            b_surf = self._font_lg.render(self._banner_text, True, NEON_YELLOW)
            pad = pygame.Rect(0, 0, b_surf.get_width() + int(36 * sc), b_surf.get_height() + int(18 * sc))
            pad.center = (cx, stage_rect.centery)
            pygame.draw.rect(self._screen, (10, 16, 36), pad, border_radius=int(12 * sc))
            pygame.draw.rect(self._screen, NEON_YELLOW, pad, max(2, int(3 * sc)), border_radius=int(12 * sc))
            self._screen.blit(b_surf, b_surf.get_rect(center=pad.center))

    def _draw_button(self, rect: pygame.Rect, label: str, color: Tuple[int, int, int]) -> None:
        mx, my = pygame.mouse.get_pos()
        hover = rect.collidepoint(mx, my)
        bg = (35, 52, 88) if hover else (22, 32, 58)
        pygame.draw.rect(self._screen, bg, rect, border_radius=max(6, int(8 * self._sc)))
        pygame.draw.rect(
            self._screen,
            color,
            rect,
            max(2, int(2 * self._sc)) if hover else 1,
            border_radius=max(6, int(8 * self._sc)),
        )
        s = self._font_sm.render(label, True, TEXT_WHITE if hover else color)
        self._screen.blit(s, s.get_rect(center=rect.center))

    def _draw_bottom_gesture_hud(self, snap: dict) -> None:
        sc = self._sc
        step = int(snap.get("combo_step", 0))
        left_charge = float(snap.get("left_charge", 0.0))
        right_charge = float(snap.get("right_charge", 0.0))
        unlock_charge = float(snap.get("unlock_charge", 0.0))
        tilt = float(snap.get("tilt", 0.0))
        cd_frac = float(snap.get("cooldown_frac", 0.0))
        cd_rem = float(snap.get("cooldown_rem", 0.0))

        # Left Swipe Wing
        lw = self._left_wing_rect
        pygame.draw.rect(self._screen, (18, 28, 50), lw, border_radius=int(12 * sc))
        if left_charge > 0.01:
            fill_w = int(lw.width * left_charge)
            fill_rect = pygame.Rect(lw.right - fill_w, lw.top, fill_w, lw.height)
            pygame.draw.rect(self._screen, (0, 110, 145), fill_rect, border_radius=int(12 * sc))
        pygame.draw.rect(
            self._screen,
            NEON_CYAN if step == 2 else (60, 80, 110),
            lw,
            max(2, int(3 * sc)) if step == 2 else 1,
            border_radius=int(12 * sc),
        )
        l_title = self._font_lg.render("◀ SWIPE LEFT", True, NEON_CYAN if step == 2 else TEXT_DIM)
        l_sub = self._font_sm.render(
            "ARMED: Swipe/Hold Left!" if step == 2 else "Locked (Flick Up 1st)",
            True,
            TEXT_WHITE if step == 2 else TEXT_DIM,
        )
        self._screen.blit(l_title, l_title.get_rect(center=(lw.centerx, lw.centery - int(11 * sc))))
        self._screen.blit(l_sub, l_sub.get_rect(center=(lw.centerx, lw.centery + int(15 * sc))))

        # Right Swipe Wing
        rw = self._right_wing_rect
        pygame.draw.rect(self._screen, (18, 28, 50), rw, border_radius=int(12 * sc))
        if right_charge > 0.01:
            fill_w = int(rw.width * right_charge)
            fill_rect = pygame.Rect(rw.left, rw.top, fill_w, rw.height)
            pygame.draw.rect(self._screen, (20, 130, 75), fill_rect, border_radius=int(12 * sc))
        pygame.draw.rect(
            self._screen,
            NEON_GREEN if step == 2 else (60, 95, 75),
            rw,
            max(2, int(3 * sc)) if step == 2 else 1,
            border_radius=int(12 * sc),
        )
        r_title = self._font_lg.render("SWIPE RIGHT ▶", True, NEON_GREEN if step == 2 else TEXT_DIM)
        r_sub = self._font_sm.render(
            "ARMED: Swipe/Hold Right!" if step == 2 else "Locked (Flick Up 1st)",
            True,
            TEXT_WHITE if step == 2 else TEXT_DIM,
        )
        self._screen.blit(r_title, r_title.get_rect(center=(rw.centerx, rw.centery - int(11 * sc))))
        self._screen.blit(r_sub, r_sub.get_rect(center=(rw.centerx, rw.centery + int(15 * sc))))

        # Center Wrist Tilt Gauge & Combo/Cooldown Bar
        mid_left = lw.right + int(16 * sc)
        mid_right = rw.left - int(16 * sc)
        mid_w = max(80, mid_right - mid_left)
        mid_cx = mid_left + mid_w // 2

        gauge_rect = pygame.Rect(mid_left, lw.top + int(14 * sc), mid_w, int(24 * sc))
        pygame.draw.rect(self._screen, (20, 26, 46), gauge_rect, border_radius=int(12 * sc))
        pygame.draw.rect(self._screen, (90, 110, 150), gauge_rect, 2, border_radius=int(12 * sc))
        pygame.draw.line(
            self._screen,
            (140, 160, 190),
            (mid_cx, gauge_rect.top),
            (mid_cx, gauge_rect.bottom),
            2,
        )

        # Wrist position dot
        clamped_tilt = max(-1.0, min(1.0, tilt))
        dot_x = int(mid_cx + clamped_tilt * (mid_w // 2 - int(14 * sc)))
        dot_col = NEON_GREEN if clamped_tilt > 0.3 else (NEON_CYAN if clamped_tilt < -0.3 else TEXT_WHITE)
        pygame.draw.circle(self._screen, dot_col, (dot_x, gauge_rect.centery), max(6, int(9 * sc)))

        # Status bar below gauge
        cd_rect = pygame.Rect(mid_left, gauge_rect.bottom + int(16 * sc), mid_w, int(14 * sc))
        pygame.draw.rect(self._screen, (25, 30, 50), cd_rect, border_radius=int(7 * sc))
        if cd_frac > 0.0:
            cd_fill = pygame.Rect(cd_rect.left, cd_rect.top, int(cd_rect.width * cd_frac), cd_rect.height)
            pygame.draw.rect(self._screen, NEON_ORANGE, cd_fill, border_radius=int(7 * sc))
            cd_lbl = f"POST-SWIPE LOCK ({cd_rem:.1f}s)"
            cd_clr = NEON_ORANGE
        elif step == 2:
            t_frac = min(1.0, float(snap.get("combo_timer", 0.0)) / 6.0)
            cd_fill = pygame.Rect(cd_rect.left, cd_rect.top, int(cd_rect.width * t_frac), cd_rect.height)
            pygame.draw.rect(self._screen, NEON_GREEN, cd_fill, border_radius=int(7 * sc))
            cd_lbl = f"🔓 ARMED ({snap.get('combo_timer', 0.0):.1f}s) — SWIPE NOW"
            cd_clr = NEON_GREEN
        else:
            if unlock_charge > 0.0:
                cd_fill = pygame.Rect(cd_rect.left, cd_rect.top, int(cd_rect.width * unlock_charge), cd_rect.height)
                pygame.draw.rect(self._screen, NEON_YELLOW, cd_fill, border_radius=int(7 * sc))
            cd_lbl = "🔒 WATCH LOCK ON (Flick Up to Unlock)"
            cd_clr = TEXT_DIM

        lbl_s = self._font_sm.render(cd_lbl, True, cd_clr)
        self._screen.blit(lbl_s, lbl_s.get_rect(center=(mid_cx, cd_rect.bottom + int(12 * sc))))
