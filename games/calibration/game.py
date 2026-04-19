"""
games/calibration/game.py — Sensor Calibration & Orientation Visualizer

Aviation-style four-panel instrument display for the MetaMotion wrist sensor.
Shows live pitch, roll, and yaw using airplane silhouettes and a compass rose.

Only available when a physical sensor is connected (mode ≠ keyboard).

Controls
────────
  ESC / BACKSPACE   → return to home screen
  SPACE / R         → reset yaw accumulator to 0°
  F                 → toggle fullscreen
"""

import math
import sys
import time
from typing import List, Tuple

import pygame
from shared.learn_test_support import draw_gesture_debug_overlay


# ── Colors ────────────────────────────────────────────────────────────────────
BG           = (12,  18,  28)
PANEL_BG     = (18,  25,  40)
PANEL_BORDER = (40,  80, 120)
SKY_CLR      = (30, 100, 180)
GROUND_CLR   = (110, 72,  22)
HORIZON_CLR  = (255, 255, 255)
PLANE_CLR    = (220, 230, 240)
PLANE_DARK   = (140, 155, 175)
ACCENT_CLR   = (0,   210, 170)
WARN_CLR     = (255, 160,  30)
TEXT_CLR     = (200, 220, 255)
DIM_CLR      = (100, 130, 170)
GREEN_CLR    = (60,  230, 130)
AMBER_CLR    = (255, 185,  50)
COMPASS_BG   = (14,  22,  42)
CARDINAL_CLR = (255, 220,  60)
TICK_CLR     = (140, 170, 200)
TICK_DIM_CLR = (60,  85, 115)
PITCH_LINE   = (200, 200, 200)

# Pre-Flight Systems Check — signal-strength gauge state colours
_PF_COLORS = [
    (220,  50,  50),   # 0 = red    "System Offline"
    (220, 180,  50),   # 1 = yellow "Signal Weak"
    ( 50, 120, 220),   # 2 = blue   "Signal Stabilizing"
    ( 50, 220, 100),   # 3 = green  "Ready for Takeoff"
]
_PF_LABELS = [
    "SEARCHING...",       # 0 — arc proxy not yet accumulated; avoids alarming "offline" flash
    "SIGNAL WEAK",        # 1
    "SIGNAL STABILIZING", # 2
    "READY FOR TAKEOFF",  # 3
]

_BEARINGS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]

def _heading_to_bearing(deg: float) -> str:
    """Convert 0-360° heading to 8-point compass label."""
    return _BEARINGS[int((deg % 360 + 22.5) / 45) % 8]


class CalibrationGame:
    """
    Real-time sensor orientation visualizer with four aviation-style panels.

    Panel layout (2 × 2):
      [Front View / Roll]     [Side View / Pitch]
      [Top View  / Yaw ]     [Sensor Data       ]
    """

    def __init__(self, screen, clock, debug=False, mode="standard", audio=None, username=""):
        self._screen   = screen
        self._clock    = clock
        self._debug    = debug
        self._mode     = mode
        self._username = username

        self._yaw_deg = 0.0          # integrated from gz
        self._last_gz = 0.0          # for smooth yaw integration
        self._mode_toast: float = 0.0
        self._mode_toast_msg: str = ""

        # Sensor fusion warmup state (only in sensor mode, not keyboard)
        self._fusion_warmup: float = 0.0    # countdown seconds remaining
        self._fusion_ready: bool = False
        self._fig8_t: float = 0.0    # animation phase for figure-8 guide

        # Pre-Flight Systems Check (BMM150 magnetometer calibration, states 0-3)
        self._pf_state: int = 0
        self._pf_prev_state: int = -1   # -1 forces initial stall-timer reset
        self._pf_stall_timer: float = 10.0
        self._pf_show_helper: bool = False
        self._pf_complete: bool = False
        self._pf_haptic_sent: bool = False
        self._pf_takeoff_t: float = 0.0   # seconds since takeoff animation started
        # Keyboard-mode simulation: auto-advance state every ~6 s
        self._pf_sim_state: int = 0
        self._pf_sim_timer: float = 6.0
        # Arc-proxy: total rotation accumulated while doing wide arcs (degrees)
        # Used when hardware sensor-fusion module isn't running (most setups).
        # Thresholds: 350° / 800° / 1400° of cumulative rotation → states 1 / 2 / 3
        self._pf_arc_total: float = 0.0

        self._init_layout()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _init_layout(self) -> None:
        sw, sh = self._screen.get_size()
        self._W, self._H = sw, sh
        self._is_fullscreen = not (sw == 800 and sh == 600)
        sc = min(sw / 800, sh / 600)
        self._sc = sc

        pw = sw // 2
        ph = sh // 2
        gap = 2

        # Four equal panels, with a narrow gap at centre
        self._panels = [
            pygame.Rect(gap,      gap,      pw - gap * 2, ph - gap * 2),   # TL
            pygame.Rect(pw + gap, gap,      sw - pw - gap * 2, ph - gap * 2),  # TR
            pygame.Rect(gap,      ph + gap, pw - gap * 2, sh - ph - gap * 2),  # BL
            pygame.Rect(pw + gap, ph + gap, sw - pw - gap * 2, sh - ph - gap * 2),  # BR
        ]

        self._font_title = pygame.font.SysFont("monospace", max(10, int(13 * sc)), bold=True)
        self._font_data  = pygame.font.SysFont("monospace", max(10, int(13 * sc)))
        self._font_label = pygame.font.SysFont("monospace", max(9,  int(11 * sc)))
        self._font_big   = pygame.font.SysFont("monospace", max(13, int(17 * sc)), bold=True)
        self._font_small = pygame.font.SysFont("monospace", max(7,  int(9  * sc)))

    def _toggle_fullscreen(self) -> None:
        self._is_fullscreen = not self._is_fullscreen
        if self._is_fullscreen:
            new_screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        else:
            new_screen = pygame.display.set_mode((800, 600))
        self._screen = new_screen
        self._init_layout()

    # ── Main loop ─────────────────────────────────────────────────────────────

    def run(self, gesture_src) -> str:
        pygame.mouse.set_visible(True)

        while True:
            dt = min(self._clock.tick(60) / 1000.0, 0.05)   # cap at 50 ms

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit()
                    sys.exit(0)
                if event.type == pygame.KEYDOWN:
                    if event.key in (pygame.K_ESCAPE, pygame.K_BACKSPACE):
                        return "home"
                    elif event.key in (pygame.K_SPACE, pygame.K_r):
                        self._yaw_deg = 0.0
                    elif event.key == pygame.K_f:
                        self._toggle_fullscreen()
                    elif event.key == pygame.K_d:
                        self._debug = not self._debug
                    elif event.key in (pygame.K_l, pygame.K_t):
                        self._mode_toast_msg = "Learn / Test mode: open Fruit Slice"
                        self._mode_toast = 2.5

            gs = gesture_src.get_state()

            ax = gs.abs_ax
            ay = gs.abs_ay
            az = gs.abs_az
            gx = gs.abs_gx
            gy = gs.abs_gy
            gz = gs.abs_gz

            # Update Pre-Flight Systems Check state machine
            self._update_pre_flight(gs, dt, gesture_src)

            # Trigger fusion warmup once calibration completes (sensor mode only)
            if (gs.calibrated and not self._fusion_ready and self._fusion_warmup <= 0.0
                    and self._mode != "keyboard"):
                self._fusion_warmup = 8.0

            # Countdown fusion warmup
            if self._fusion_warmup > 0.0:
                self._fusion_warmup = max(0.0, self._fusion_warmup - dt)
                self._fig8_t += dt
                if self._fusion_warmup <= 0.0:
                    self._fusion_ready = True

            # Integrate gz as fallback yaw (drifts without magnetometer)
            self._yaw_deg = (self._yaw_deg + gz * dt) % 360.0
            # Hardware compass heading (Bosch KF + BMM150) overrides when fusion is active
            yaw_display = gs.hw_heading if gs.hw_fusion_valid else self._yaw_deg
            if self._mode_toast > 0:
                self._mode_toast = max(0.0, self._mode_toast - dt)

            # Compute pitch and roll from gravity vector
            #   Pitch: positive = nose up (ax shifts negative when tilted forward)
            #   Roll:  positive = right wing down (ay shifts positive)
            pitch_deg = math.degrees(math.atan2(-ax, math.sqrt(ay ** 2 + az ** 2)))
            roll_deg  = math.degrees(math.atan2(ay, az))

            # Use hardware Euler angles when fusion is active, else trig fallback
            pitch_display = gs.euler_pitch if gs.hw_fusion_valid else pitch_deg
            roll_display  = gs.euler_roll  if gs.hw_fusion_valid else roll_deg

            self._draw(ax, ay, az, gx, gy, gz,
                       pitch_display, roll_display, yaw_display, gs.calibrated, gs)
            if self._debug:
                draw_gesture_debug_overlay(
                    self._screen, gs, self._W, self._H, self._sc, self._font_big)
                self._draw_sensor_status_overlay(gs)
            if self._mode_toast > 0:
                sc    = self._sc
                alpha = min(255, int(self._mode_toast / 2.5 * 255))
                ts    = self._font_label.render(self._mode_toast_msg, True, (200, 200, 255))
                ts.set_alpha(alpha)
                self._screen.blit(ts, ts.get_rect(
                    center=(self._W // 2, self._H - max(20, int(24 * sc)))))
            pygame.display.flip()

        return "home"

    # ── Top-level draw ────────────────────────────────────────────────────────

    def _draw(self, ax, ay, az, gx, gy, gz,
              pitch, roll, yaw, calibrated, gs=None) -> None:
        self._screen.fill(BG)
        self._draw_dividers()

        # Panel inner areas (below title bar)
        title_h = max(18, int(22 * self._sc))
        inners = [
            pygame.Rect(p.left + 2, p.top + title_h, p.width - 4, p.height - title_h - 2)
            for p in self._panels
        ]

        self._draw_panel_header(self._panels[0], "FRONT VIEW  •  ROLL",  (0, 180, 255))
        self._draw_panel_header(self._panels[1], "SIDE VIEW  •  PITCH",  (100, 255, 160))
        hw_active = gs.hw_fusion_valid if gs else False
        compass_hdr = "TOP VIEW  •  COMPASS" if hw_active else "TOP VIEW  •  YAW"
        self._draw_panel_header(self._panels[2], compass_hdr,  AMBER_CLR)
        self._draw_panel_header(self._panels[3], "SENSOR DATA",          ACCENT_CLR)

        self._draw_front_view(inners[0], roll)
        self._draw_side_view(inners[1], pitch)
        self._draw_top_view(inners[2], yaw, hw_active=hw_active)
        self._draw_data_panel(inners[3], ax, ay, az, gx, gy, gz, pitch, roll, yaw, gs)

        if not calibrated:
            self._draw_calibrating_overlay()

        if self._fusion_warmup > 0.0:
            self._draw_fusion_warmup_overlay(self._fusion_warmup)

        # Pre-Flight Systems Check overlays (shown after IMU calibration settles)
        if calibrated and self._fusion_warmup <= 0.0:
            if self._pf_complete and self._pf_takeoff_t < 4.0:
                self._draw_takeoff_animation()
            elif not self._pf_complete:
                self._draw_pre_flight_overlay()

    def _draw_dividers(self) -> None:
        sw, sh = self._W, self._H
        pygame.draw.line(self._screen, PANEL_BORDER, (sw // 2, 0), (sw // 2, sh), 2)
        pygame.draw.line(self._screen, PANEL_BORDER, (0, sh // 2), (sw, sh // 2), 2)

    def _draw_panel_header(self, panel: pygame.Rect,
                           title: str, color: tuple) -> None:
        pygame.draw.rect(self._screen, PANEL_BG, panel)
        pygame.draw.rect(self._screen, PANEL_BORDER, panel, 1)
        surf = self._font_title.render(title, True, color)
        self._screen.blit(surf, (panel.left + 6, panel.top + 3))

    # ── Helper: circular attitude indicator background ────────────────────────

    def _draw_ai_circle(self, cx: int, cy: int, r: int,
                        roll_rad: float = 0.0,
                        pitch_offset_px: float = 0.0) -> None:
        """
        Draw a circular attitude-indicator background (sky + ground) onto
        self._screen, centred at (cx, cy) with radius r.

        roll_rad          — rotation of the sky/ground backdrop (roll)
        pitch_offset_px   — vertical shift of the horizon (positive = nose up)
        """
        diam = r * 2 + 4
        scene = pygame.Surface((diam, diam))
        scx, scy = r + 2, r + 2

        # Fill with sky
        scene.fill(SKY_CLR)

        # Ground polygon (large rotated lower-half rectangle, shifted by pitch)
        ground_pts = self._rotated_half_rect(scx, scy - pitch_offset_px,
                                             r * 5, r * 5, roll_rad, upper=False)
        pygame.draw.polygon(scene, GROUND_CLR, ground_pts)

        # Pitch-degree reference lines (drawn on the rotated scene)
        px_per_deg = r / 70.0
        for deg in (-30, -20, -10, 10, 20, 30):
            offset = -deg * px_per_deg - pitch_offset_px
            cos_r  = math.cos(roll_rad)
            sin_r  = math.sin(roll_rad)
            hw = r * (0.35 if abs(deg) == 30 else 0.22)
            lx = scx - hw * cos_r - offset * sin_r
            ly = scy - hw * sin_r + offset * cos_r
            rx = scx + hw * cos_r - offset * sin_r
            ry = scy + hw * sin_r + offset * cos_r
            pygame.draw.line(scene, PITCH_LINE + (180,),
                             (int(lx), int(ly)), (int(rx), int(ry)), 1)
            label_surf = self._font_small.render(f"{deg:+d}", True, PITCH_LINE)
            scene.blit(label_surf, (int(rx) + 2, int(ry) - 5))

        # Horizon line
        cos_r = math.cos(roll_rad)
        sin_r = math.sin(roll_rad)
        hx1 = scx - r * cos_r + pitch_offset_px * sin_r
        hy1 = scy - r * sin_r - pitch_offset_px * cos_r
        hx2 = scx + r * cos_r + pitch_offset_px * sin_r
        hy2 = scy + r * sin_r - pitch_offset_px * cos_r
        pygame.draw.line(scene, HORIZON_CLR,
                         (int(hx1), int(hy1)), (int(hx2), int(hy2)), 2)

        # Circular mask
        scene_alpha = scene.convert_alpha()
        mask = pygame.Surface((diam, diam), pygame.SRCALPHA)
        mask.fill((0, 0, 0, 0))
        pygame.draw.circle(mask, (255, 255, 255, 255), (scx, scy), r)
        scene_alpha.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)

        self._screen.blit(scene_alpha, (cx - r - 2, cy - r - 2))
        pygame.draw.circle(self._screen, PANEL_BORDER, (cx, cy), r, 2)

    @staticmethod
    def _rotated_half_rect(cx, cy, w, h, angle, upper=True):
        """Upper or lower half of a rectangle, rotated around (cx, cy)."""
        pts = [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, 0), (-w / 2, 0)] if upper \
            else [(-w / 2, 0), (w / 2, 0), (w / 2, h / 2), (-w / 2, h / 2)]
        cos_a, sin_a = math.cos(angle), math.sin(angle)
        return [(cx + x * cos_a - y * sin_a, cy + x * sin_a + y * cos_a)
                for (x, y) in pts]

    # ── Panel 1 — Front View (Roll) ───────────────────────────────────────────

    def _draw_front_view(self, area: pygame.Rect, roll_deg: float) -> None:
        cx, cy = area.centerx, area.centery - max(8, int(12 * self._sc))
        r = min(area.width, area.height) // 2 - max(4, int(8 * self._sc))

        self._draw_ai_circle(cx, cy, r, roll_rad=math.radians(roll_deg))

        # Fixed airplane symbol (seen from front — horizontal wings, body)
        wing_w = int(r * 0.55)
        wing_h = max(3, int(r * 0.07))
        body_h = max(6, int(r * 0.30))
        body_w = max(3, int(r * 0.07))

        # Wings
        pygame.draw.rect(self._screen, PLANE_CLR,
                         (cx - wing_w, cy - wing_h // 2, wing_w * 2, wing_h))
        # Wing tips (darker)
        tip_w = max(2, int(r * 0.10))
        pygame.draw.rect(self._screen, PLANE_DARK,
                         (cx - wing_w, cy - wing_h // 2, tip_w, wing_h))
        pygame.draw.rect(self._screen, PLANE_DARK,
                         (cx + wing_w - tip_w, cy - wing_h // 2, tip_w, wing_h))
        # Fuselage stub
        pygame.draw.rect(self._screen, PLANE_CLR,
                         (cx - body_w // 2, cy - body_h // 2, body_w, body_h))
        # Centre dot
        pygame.draw.circle(self._screen, AMBER_CLR, (cx, cy), max(3, int(r * 0.06)))

        # Roll angle label
        lbl = self._font_label.render(f"Roll:  {roll_deg:+.1f}°", True, TEXT_CLR)
        self._screen.blit(lbl, lbl.get_rect(centerx=cx,
                                             top=area.bottom - max(16, int(18 * self._sc))))

    # ── Panel 2 — Side View (Pitch) ───────────────────────────────────────────

    def _draw_side_view(self, area: pygame.Rect, pitch_deg: float) -> None:
        cx, cy = area.centerx, area.centery - max(8, int(12 * self._sc))
        r = min(area.width, area.height) // 2 - max(4, int(8 * self._sc))

        px_per_deg    = r / 70.0
        pitch_offset  = pitch_deg * px_per_deg   # positive pitch → horizon goes down

        self._draw_ai_circle(cx, cy, r, roll_rad=0.0,
                             pitch_offset_px=pitch_offset)

        # Fixed airplane side profile
        self._draw_airplane_side(cx, cy, r)

        lbl = self._font_label.render(f"Pitch: {pitch_deg:+.1f}°", True, TEXT_CLR)
        self._screen.blit(lbl, lbl.get_rect(centerx=cx,
                                             top=area.bottom - max(16, int(18 * self._sc))))

    def _draw_airplane_side(self, cx: int, cy: int, r: int) -> None:
        sc = r / 58.0
        # Fuselage bar
        fl, fr = int(cx - 38 * sc), int(cx + 32 * sc)
        fw = max(3, int(7 * sc))
        pygame.draw.rect(self._screen, PLANE_CLR,
                         (fl, cy - fw // 2, fr - fl, fw), border_radius=max(2, int(3 * sc)))
        # Nose cone
        pygame.draw.polygon(self._screen, PLANE_CLR, [
            (fl, cy - fw // 2), (fl, cy + fw // 2),
            (int(fl - 10 * sc), cy),
        ])
        # Wing
        pygame.draw.polygon(self._screen, PLANE_CLR, [
            (int(cx - 8 * sc),  cy),
            (int(cx - 25 * sc), int(cy + 20 * sc)),
            (int(cx + 12 * sc), cy),
        ])
        # Vertical tail fin
        pygame.draw.polygon(self._screen, PLANE_CLR, [
            (int(cx + 28 * sc), cy),
            (int(cx + 32 * sc), cy),
            (int(cx + 30 * sc), int(cy - 18 * sc)),
        ])
        # Horizontal tail
        pygame.draw.polygon(self._screen, PLANE_CLR, [
            (int(cx + 24 * sc), cy),
            (int(cx + 32 * sc), cy),
            (int(cx + 32 * sc), int(cy + 7 * sc)),
            (int(cx + 18 * sc), int(cy + 6 * sc)),
        ])
        # Cockpit
        pygame.draw.circle(self._screen, (140, 195, 255),
                           (int(fl + 6 * sc), cy), max(4, int(7 * sc)))
        # Centre marker
        pygame.draw.circle(self._screen, AMBER_CLR, (cx, cy), 3)

    # ── Panel 3 — Top View (Yaw / Compass) ───────────────────────────────────

    def _draw_top_view(self, area: pygame.Rect, yaw_deg: float, hw_active: bool = False) -> None:
        cx, cy = area.centerx, area.centery - max(6, int(10 * self._sc))
        r = min(area.width, area.height) // 2 - max(4, int(8 * self._sc))

        # Compass background
        pygame.draw.circle(self._screen, COMPASS_BG, (cx, cy), r)
        pygame.draw.circle(self._screen, PANEL_BORDER, (cx, cy), r, 2)

        # Subtle concentric ring
        pygame.draw.circle(self._screen, PANEL_BORDER, (cx, cy), int(r * 0.6), 1)

        # Tick marks (every 10°; labelled at 30°, thick at 90°)
        for i in range(0, 360, 10):
            angle = math.radians(i - 90)   # 0° = North = top
            if i % 90 == 0:
                tick_len, color, width = r * 0.18, CARDINAL_CLR, 2
            elif i % 30 == 0:
                tick_len, color, width = r * 0.11, TICK_CLR, 1
            else:
                tick_len, color, width = r * 0.055, TICK_DIM_CLR, 1
            x1 = cx + (r - tick_len) * math.cos(angle)
            y1 = cy + (r - tick_len) * math.sin(angle)
            x2 = cx + r * math.cos(angle)
            y2 = cy + r * math.sin(angle)
            pygame.draw.line(self._screen, color,
                             (int(x1), int(y1)), (int(x2), int(y2)), width)

        # Cardinal labels
        label_r = r - max(14, int(22 * self._sc))
        for label, deg in [("N", 0), ("E", 90), ("S", 180), ("W", 270)]:
            angle = math.radians(deg - 90)
            lx = cx + label_r * math.cos(angle)
            ly = cy + label_r * math.sin(angle)
            surf = self._font_big.render(label, True, CARDINAL_CLR)
            self._screen.blit(surf, surf.get_rect(center=(int(lx), int(ly))))

        # Intercardinal labels
        for label, deg in [("NE", 45), ("SE", 135), ("SW", 225), ("NW", 315)]:
            angle = math.radians(deg - 90)
            lx = cx + label_r * math.cos(angle)
            ly = cy + label_r * math.sin(angle)
            surf = self._font_small.render(label, True, TICK_CLR)
            self._screen.blit(surf, surf.get_rect(center=(int(lx), int(ly))))

        # Airplane top silhouette (rotates with yaw)
        self._draw_airplane_top(cx, cy, r, yaw_deg)

        if hw_active:
            bearing = _heading_to_bearing(yaw_deg)
            lbl_txt = f"Heading: {yaw_deg:.1f}°  {bearing}  [COMPASS]"
            lbl_clr = GREEN_CLR
        else:
            lbl_txt = f"Yaw: {yaw_deg:.1f}°  SPACE=reset  [gyro]"
            lbl_clr = TEXT_CLR
        lbl = self._font_label.render(lbl_txt, True, lbl_clr)
        self._screen.blit(lbl, lbl.get_rect(
            centerx=cx, top=area.bottom - max(16, int(18 * self._sc))))

    def _draw_airplane_top(self, cx: int, cy: int, r: int, yaw_deg: float) -> None:
        """Top-down airplane silhouette, rotated so 0° = pointing North (up)."""
        sc  = r / 58.0
        yaw_rad = math.radians(yaw_deg - 90)   # -90 → 0° aligns to top

        def rot(x, y):
            cos_a = math.cos(yaw_rad)
            sin_a = math.sin(yaw_rad)
            return (int(cx + x * cos_a - y * sin_a),
                    int(cy + x * sin_a + y * cos_a))

        # Fuselage (nose at top / -y direction)
        fuse = [
            rot(0,           -34 * sc),   # nose
            rot(5  * sc,     -18 * sc),
            rot(6  * sc,      12 * sc),
            rot(0,            28 * sc),   # tail tip
            rot(-6 * sc,      12 * sc),
            rot(-5 * sc,     -18 * sc),
        ]
        pygame.draw.polygon(self._screen, PLANE_CLR, fuse)

        # Main wings
        wing_l = [
            rot(-5  * sc,  -6 * sc),
            rot(-34 * sc,   4 * sc),
            rot(-28 * sc,  10 * sc),
            rot(-3  * sc,   2 * sc),
        ]
        wing_r = [
            rot( 5  * sc,  -6 * sc),
            rot( 34 * sc,   4 * sc),
            rot( 28 * sc,  10 * sc),
            rot( 3  * sc,   2 * sc),
        ]
        pygame.draw.polygon(self._screen, PLANE_CLR, wing_l)
        pygame.draw.polygon(self._screen, PLANE_CLR, wing_r)

        # Horizontal tail fins
        tail_l = [
            rot(-3  * sc,  18 * sc),
            rot(-15 * sc,  26 * sc),
            rot(-13 * sc,  30 * sc),
            rot(-2  * sc,  23 * sc),
        ]
        tail_r = [
            rot( 3  * sc,  18 * sc),
            rot( 15 * sc,  26 * sc),
            rot( 13 * sc,  30 * sc),
            rot( 2  * sc,  23 * sc),
        ]
        pygame.draw.polygon(self._screen, PLANE_CLR, tail_l)
        pygame.draw.polygon(self._screen, PLANE_CLR, tail_r)

        # Nose & cockpit dots
        pygame.draw.circle(self._screen, (140, 195, 255), rot(0, -28 * sc), max(3, int(4 * sc)))
        pygame.draw.circle(self._screen, ACCENT_CLR, (cx, cy), max(3, int(4 * sc)))

    # ── Panel 4 — Sensor Data ─────────────────────────────────────────────────

    def _draw_data_panel(self, area: pygame.Rect,
                         ax, ay, az, gx, gy, gz,
                         pitch, roll, yaw, gs=None) -> None:
        lh = max(14, int(16 * self._sc))
        y = area.top + 4
        x = area.left + 8

        # Prepare fusion data (with defaults for keyboard mode)
        euler_roll = gs.euler_roll if gs and gs.euler_roll != 0.0 else 0.0
        euler_pitch = gs.euler_pitch if gs and gs.euler_pitch != 0.0 else 0.0
        euler_yaw = gs.euler_yaw if gs and gs.euler_yaw != 0.0 else 0.0
        av_mag = gs.av_magnitude if gs else 0.0
        qw = gs.qw if gs else 1.0
        qx = gs.qx if gs else 0.0
        qy = gs.qy if gs else 0.0
        qz = gs.qz if gs else 0.0
        # Magnetometer / hardware fusion data
        hw_heading_val  = gs.hw_heading      if gs else 0.0
        hw_valid        = gs.hw_fusion_valid if gs else False
        mag_cal         = gs.mag_cal_state   if gs else 0
        _CAL_LABELS = ["UNCAL", "WEAK", "GOOD", "LOCKED"]
        bearing_str = _heading_to_bearing(hw_heading_val) if hw_valid else "---"

        rows = [
            ("ATTITUDE",              None,       None),
            ("  Pitch",   f"{pitch:+7.1f} °",    GREEN_CLR),
            ("  Roll ",   f"{roll:+7.1f} °",     GREEN_CLR),
            ("  Yaw  ",   f"{yaw:+7.1f} °",      GREEN_CLR),
            ("",                      None,       None),
            ("ACCELEROMETER",         None,       None),
            ("  ax",      f"{ax:+7.3f} g",       TEXT_CLR),
            ("  ay",      f"{ay:+7.3f} g",       TEXT_CLR),
            ("  az",      f"{az:+7.3f} g",       TEXT_CLR),
            ("",                      None,       None),
            ("GYROSCOPE",             None,       None),
            ("  gx",      f"{gx:+7.1f} °/s",     TEXT_CLR),
            ("  gy",      f"{gy:+7.1f} °/s",     TEXT_CLR),
            ("  gz",      f"{gz:+7.1f} °/s",     TEXT_CLR),
            ("",                      None,       None),
            ("SENSOR FUSION",         None,       None),
            ("  Roll ",   f"{euler_roll:+7.1f} °",   (100, 220, 255)),
            ("  Pitch",   f"{euler_pitch:+7.1f} °",  (100, 220, 255)),
            ("  Yaw  ",   f"{euler_yaw:+7.1f} °",    (80, 170, 200)),
            ("  AV mag",  f"{av_mag:+7.1f} °/s",     TEXT_CLR),
            (f"  q={qw:+.2f},{qx:+.2f},{qy:+.2f},{qz:+.2f}", None, DIM_CLR),
            ("",                      None,       None),
            ("",                      None,       None),
            ("MAGNETOMETER",          None,       None),
            ("  Heading", f"{hw_heading_val:7.1f}°  {bearing_str}",
                          GREEN_CLR if hw_valid else DIM_CLR),
            ("  Cal",     f"{mag_cal}/3  {_CAL_LABELS[mag_cal]}",
                          _PF_COLORS[mag_cal]),
            ("  Source",  "HW COMPASS" if hw_valid else "SW FALLBACK",
                          GREEN_CLR if hw_valid else WARN_CLR),
            ("",                      None,       None),
            ("CONTROLS",              None,       None),
            ("  ESC",     "home",                DIM_CLR),
            ("  SPACE",   "reset yaw",           DIM_CLR),
            ("  F",       "fullscreen",          DIM_CLR),
        ]

        for label, value, color in rows:
            if not label:
                y += lh // 2
                continue
            if value is None:
                # Section header or info-only label
                surf = self._font_data.render(label, True, color if color else ACCENT_CLR)
                self._screen.blit(surf, (x, y))
            else:
                # Label + value pair
                lsurf = self._font_data.render(label, True, DIM_CLR)
                vsurf = self._font_data.render(value, True, color)
                self._screen.blit(lsurf, (x, y))
                self._screen.blit(vsurf, (x + lsurf.get_width() + 4, y))
            y += lh
            if y > area.bottom - lh:
                break

    # ── Pre-Flight Systems Check ──────────────────────────────────────────────

    def _update_pre_flight(self, gs, dt: float, gesture_src) -> None:
        """State-machine for BMM150 magnetometer calibration progress.

        Priority order for effective_state:
          1. Real hardware mag_cal_state (BLE sensor-fusion module, 0x19) if > 0
          2. Arc-proxy: total rotation °, thresholds 350/800/1400 → states 1/2/3
          3. Timer fallback for keyboard mode (av_magnitude is always 0)
        """
        if self._mode == "keyboard":
            # No sensor — advance on a timer so the demo is still playable
            self._pf_sim_timer -= dt
            if self._pf_sim_timer <= 0.0 and self._pf_sim_state < 3:
                self._pf_sim_state += 1
                self._pf_sim_timer = 6.0
            effective_state = self._pf_sim_state
        elif gs.mag_cal_state > 0:
            # Hardware sensor-fusion module is responding — use the real value
            effective_state = gs.mag_cal_state
        else:
            # Sensor-fusion module not started or no magnetometer on this variant.
            # Use cumulative angular velocity as a proxy: the child steering in
            # wide arcs accumulates degrees and advances through the states.
            _ARC_THRESHOLDS = (350.0, 800.0, 1400.0)  # °  for states 1, 2, 3
            self._pf_arc_total += gs.av_magnitude * dt
            if self._pf_arc_total >= _ARC_THRESHOLDS[2]:
                effective_state = 3
            elif self._pf_arc_total >= _ARC_THRESHOLDS[1]:
                effective_state = 2
            elif self._pf_arc_total >= _ARC_THRESHOLDS[0]:
                effective_state = 1
            else:
                effective_state = 0

        # Reset stall timer whenever the state advances
        if effective_state != self._pf_prev_state:
            self._pf_stall_timer = 10.0
            self._pf_show_helper = False
            self._pf_prev_state  = effective_state
        self._pf_state = effective_state

        if not self._pf_complete:
            if effective_state < 3:
                self._pf_stall_timer = max(0.0, self._pf_stall_timer - dt)
                if self._pf_stall_timer <= 0.0:
                    self._pf_show_helper = True
                    self._pf_stall_timer = 10.0  # re-arm so the prompt doesn't flicker
            else:
                self._pf_complete = True
                if not self._pf_haptic_sent:
                    self._pf_haptic_sent = True
                    gesture_src.vibrate(0.5)
                    # Only write to NVM if hardware sensor-fusion provided real cal data
                    # (gs.mag_cal_state > 0). Sending the NVM write without sensor fusion
                    # running can reconfigure the gyro and break all subsequent streaming.
                    if gs.mag_cal_state > 0:
                        gesture_src.save_calibration_to_nvm()

        if self._pf_complete:
            self._pf_takeoff_t += dt

    def _draw_signal_gauge(self, cx: int, cy: int, state: int) -> None:
        """
        Draw 4 vertical signal-strength bars (like a mobile signal icon).
        Bars 1-4 light up progressively as state 0→3 is reached.
        """
        sc    = self._sc
        n     = 4
        bar_w = max(10, int(18 * sc))
        gap   = max(4,  int(7  * sc))
        total_w = n * bar_w + (n - 1) * gap
        base_h  = max(12, int(20 * sc))   # shortest bar height step

        color_active = _PF_COLORS[min(state, 3)]
        color_dim    = (35, 50, 70)

        for i in range(n):
            bar_h  = base_h * (i + 1)
            bx     = cx - total_w // 2 + i * (bar_w + gap)
            by     = cy - bar_h
            filled = i < (state + 1)   # bar i is lit when state >= i
            color  = color_active if filled else color_dim
            pygame.draw.rect(self._screen, color,
                             (bx, by, bar_w, bar_h), border_radius=max(2, int(3 * sc)))

    def _draw_pre_flight_overlay(self) -> None:
        """Semi-transparent 'Pre-Flight Systems Check' overlay with signal gauge and prompts."""
        overlay = pygame.Surface((self._W, self._H), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 165))
        self._screen.blit(overlay, (0, 0))

        cx, cy = self._W // 2, self._H // 2
        sc = self._sc

        # Title
        title = self._font_big.render("PRE-FLIGHT SYSTEMS CHECK", True, ACCENT_CLR)
        self._screen.blit(title, title.get_rect(center=(cx, int(cy - 110 * sc))))

        sub = self._font_label.render("Drone Pilot Dashboard  •  Compass Lock", True, DIM_CLR)
        self._screen.blit(sub, sub.get_rect(center=(cx, int(cy - 85 * sc))))

        # Signal-strength gauge (vertical bars)
        gauge_cy = int(cy - 30 * sc)
        self._draw_signal_gauge(cx, gauge_cy, self._pf_state)

        # Gauge bar labels (tiny, below the bars)
        bar_labels = ["0", "1", "2", "3"]
        n, bar_w, gap = 4, max(10, int(18 * sc)), max(4, int(7 * sc))
        total_w = n * bar_w + (n - 1) * gap
        base_h_max = max(12, int(20 * sc)) * n  # tallest bar height for spacing
        for i, lbl in enumerate(bar_labels):
            lx = cx - total_w // 2 + i * (bar_w + gap) + bar_w // 2
            ly = gauge_cy + max(4, int(6 * sc))
            s  = self._font_small.render(lbl, True, DIM_CLR)
            self._screen.blit(s, s.get_rect(centerx=lx, top=ly))

        # State label (colour-coded)
        label_color = _PF_COLORS[min(self._pf_state, 3)]
        lbl = self._font_big.render(_PF_LABELS[min(self._pf_state, 3)], True, label_color)
        self._screen.blit(lbl, lbl.get_rect(center=(cx, int(cy + 20 * sc))))

        # Stall timer progress bar (10 s countdown until helper prompt)
        if not self._pf_show_helper:
            pct  = self._pf_stall_timer / 10.0
            bw   = int(260 * sc)
            bh   = max(5, int(7 * sc))
            bx   = cx - bw // 2
            by   = int(cy + 45 * sc)
            pygame.draw.rect(self._screen, (30, 45, 65), (bx, by, bw, bh), border_radius=3)
            pygame.draw.rect(self._screen, label_color,  (bx, by, int(bw * pct), bh), border_radius=3)
            hint = self._font_small.render("Steer the drone in wide arcs!", True, TEXT_CLR)
            self._screen.blit(hint, hint.get_rect(center=(cx, int(cy + 60 * sc))))

        # Helper prompt (shown when child stalls for 10 s without progress)
        if self._pf_show_helper:
            hbg = pygame.Surface((int(480 * sc), int(75 * sc)), pygame.SRCALPHA)
            hbg.fill((255, 200, 0, 45))
            self._screen.blit(hbg, hbg.get_rect(center=(cx, int(cy + 65 * sc))))
            h1 = self._font_data.render("Ask an adult to help!", True, AMBER_CLR)
            h2 = self._font_label.render(
                "Hold the sensor and rotate in a full 360° circle.", True, TEXT_CLR)
            self._screen.blit(h1, h1.get_rect(center=(cx, int(cy + 52 * sc))))
            self._screen.blit(h2, h2.get_rect(center=(cx, int(cy + 74 * sc))))

    def _draw_takeoff_animation(self) -> None:
        """High-contrast 'Ready for Takeoff' success animation with rising airplane."""
        t  = self._pf_takeoff_t
        sc = self._sc
        cx, cy = self._W // 2, self._H // 2

        # High-contrast dark-green background
        bg = pygame.Surface((self._W, self._H))
        bg.fill((0, 18, 8))
        self._screen.blit(bg, (0, 0))

        # Pulsing "READY FOR TAKEOFF!" headline
        pulse = 0.5 + 0.5 * math.sin(t * 5.0)
        g_val = int(180 + 75 * pulse)
        headline = self._font_big.render("READY FOR TAKEOFF!", True, (50, g_val, 80))
        self._screen.blit(headline, headline.get_rect(center=(cx, int(cy - 70 * sc))))

        # Confirmation message (fades in at 1.5 s)
        if t > 1.5:
            fade      = min(1.0, (t - 1.5) / 0.5)
            save_surf = self._font_data.render(
                "Compass lock achieved — calibration complete!", True, GREEN_CLR)
            save_surf.set_alpha(int(fade * 220))
            self._screen.blit(save_surf, save_surf.get_rect(center=(cx, int(cy - 38 * sc))))

        # Animated airplane rising from bottom toward top
        rise   = min(t / 3.0, 1.0)
        ease   = rise * rise * (3.0 - 2.0 * rise)   # smoothstep
        plane_y = int(self._H * 0.88 - (self._H * 0.80) * ease)
        r_plane = max(20, int(48 * sc))
        self._draw_airplane_top(cx, plane_y, r_plane, yaw_deg=0.0)

        # Vapour-trail dots
        n_trail = 6
        for i in range(n_trail):
            trail_y = plane_y + int((i + 1) * 22 * sc)
            alpha_t = max(0, 180 - i * 30)
            dot_r   = max(2, int((n_trail - i) * 2 * sc))
            dot_s   = pygame.Surface((dot_r * 2, dot_r * 2), pygame.SRCALPHA)
            pygame.draw.circle(dot_s, (50, 220, 100, alpha_t), (dot_r, dot_r), dot_r)
            self._screen.blit(dot_s, (cx - dot_r, trail_y - dot_r))

        # "Signal: LOCKED" indicator bottom-centre
        lock_surf = self._font_label.render("SIGNAL LOCKED  ●  STATE 3 / 3", True, GREEN_CLR)
        self._screen.blit(lock_surf, lock_surf.get_rect(
            center=(cx, self._H - max(20, int(28 * sc)))))

    # ── Calibrating overlay ───────────────────────────────────────────────────

    def _draw_calibrating_overlay(self) -> None:
        overlay = pygame.Surface((self._W, self._H), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 170))
        self._screen.blit(overlay, (0, 0))

        cx, cy = self._W // 2, self._H // 2
        t = self._font_big.render("CALIBRATING…", True, WARN_CLR)
        s = self._font_data.render(
            "Hold the sensor still to establish neutral orientation.", True, TEXT_CLR)
        self._screen.blit(t, t.get_rect(center=(cx, cy - 18)))
        self._screen.blit(s, s.get_rect(center=(cx, cy + 16)))

    # ── Sensor Fusion Warmup Overlay ───────────────────────────────────────────

    def _draw_fusion_warmup_overlay(self, warmup_remaining: float) -> None:
        """
        Semi-transparent overlay with animated figure-8 guidance and countdown.
        Shows during the 8-second fusion sensor convergence phase.
        """
        overlay = pygame.Surface((self._W, self._H), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 140))
        self._screen.blit(overlay, (0, 0))

        cx, cy = self._W // 2, self._H // 2
        sc = self._sc

        # Title
        title = self._font_big.render("SENSOR FUSION WARMING UP", True, ACCENT_CLR)
        self._screen.blit(title, title.get_rect(center=(cx, int(cy - 90 * sc))))

        # Instructions
        sub = self._font_data.render(
            "Move sensor in a figure-8 pattern to initialize orientation",
            True, TEXT_CLR)
        self._screen.blit(sub, sub.get_rect(center=(cx, int(cy - 60 * sc))))

        # Animated Lissajous figure-8 guide
        # x = A * sin(t + π/2), y = B * sin(2t)
        A = int(120 * sc)
        B = int(60 * sc)
        N = 120  # path sample points
        pts = []
        for i in range(N + 1):
            phase = 2 * math.pi * i / N
            px = cx + int(A * math.sin(phase + math.pi / 2))
            py = int(cy + 20 * sc) + int(B * math.sin(2 * phase))
            pts.append((px, py))

        # Draw dim guide path
        for i in range(1, len(pts)):
            pygame.draw.line(self._screen, (60, 120, 180), pts[i-1], pts[i], 2)

        # Animated dot following the figure-8
        dot_phase = (self._fig8_t * 0.9) % (2 * math.pi)  # ~7.2 seconds per loop
        dot_x = cx + int(A * math.sin(dot_phase + math.pi / 2))
        dot_y = int(cy + 20 * sc) + int(B * math.sin(2 * dot_phase))
        pygame.draw.circle(self._screen, ACCENT_CLR, (dot_x, dot_y), max(5, int(8 * sc)))

        # Countdown timer
        countdown = self._font_big.render(f"{warmup_remaining:.0f}s", True, WARN_CLR)
        self._screen.blit(countdown, countdown.get_rect(
            center=(cx, int(cy + 100 * sc))))

    # ── Debug: sensor status overlay ─────────────────────────────────────────

    def _draw_sensor_status_overlay(self, gs) -> None:
        """Debug panel (top-right): lists every sensor with ACTIVE / INACTIVE status."""
        sc = self._sc
        lh = max(17, int(20 * sc))
        pad = max(5, int(7 * sc))

        _CAL_COLORS = [(220, 50, 50), (220, 180, 50), (50, 120, 220), (50, 220, 100)]
        _CAL_LABEL  = ["UNCAL", "WEAK", "GOOD", "LOCKED"]

        acc_on  = gs.calibrated
        gyro_on = gs.calibrated and gs.av_magnitude >= 0   # always true once calibrated
        sf_on   = gs.hw_fusion_valid
        mag_on  = gs.hw_fusion_valid   # BMM150 is fed through module 0x19
        cal     = gs.mag_cal_state

        # Each entry: (chip label, description, active, colour-when-on)
        rows = [
            ("Accelerometer", "BMI160/270  mod 0x03", acc_on,  (100, 200, 255)),
            ("Gyroscope",     "BMI160/270  mod 0x13", gyro_on, (100, 200, 255)),
            ("Sensor Fusion", "Bosch KF    mod 0x19", sf_on,   ( 80, 255, 180)),
            ("Magnetometer",  "BMM150      via 0x19", mag_on,  ( 80, 255, 180)),
        ]

        # Measure widest line to size the panel
        test_line = "Sensor Fusion  INACTIVE  [Bosch KF    mod 0x19]"
        tw = self._font_label.size(test_line)[0]
        panel_w = tw + pad * 2
        # rows + header + cal row + heading row + bottom pad
        n_lines = len(rows) + 3
        panel_h = lh * n_lines + pad * 2 + lh

        # Position: top-right, below gesture debug bar (~64 px)
        gesture_bar_h = max(48, int(64 * sc))
        px = self._W - panel_w - pad
        py = gesture_bar_h + pad

        bg = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
        bg.fill((0, 0, 0, 200))
        pygame.draw.rect(bg, (40, 80, 120, 230), (0, 0, panel_w, panel_h), 1)
        self._screen.blit(bg, (px, py))

        y = py + pad

        # Header
        hdr = self._font_data.render("SENSOR STATUS", True, ACCENT_CLR)
        self._screen.blit(hdr, (px + pad, y))
        y += lh

        # Separator line
        pygame.draw.line(self._screen, PANEL_BORDER,
                         (px + pad, y - 3), (px + panel_w - pad, y - 3), 1)

        for name, chip, active, on_clr in rows:
            dot    = "●" if active else "○"
            status = "ACTIVE  " if active else "INACTIVE"
            clr    = on_clr if active else (90, 90, 90)
            line   = f"{dot} {name:<15}  {status}  [{chip}]"
            surf   = self._font_label.render(line, True, clr)
            self._screen.blit(surf, (px + pad, y))
            y += lh

        # Separator
        pygame.draw.line(self._screen, PANEL_BORDER,
                         (px + pad, y - 2), (px + panel_w - pad, y - 2), 1)

        # Calibration state
        cal_clr  = _CAL_COLORS[min(cal, 3)]
        cal_text = f"  Mag Cal:  {cal}/3  {_CAL_LABEL[min(cal, 3)]}"
        self._screen.blit(
            self._font_label.render(cal_text, True, cal_clr), (px + pad, y))
        y += lh

        # Hardware heading (only meaningful when fusion active)
        if sf_on:
            bearing  = _heading_to_bearing(gs.hw_heading)
            hdg_text = f"  Heading:  {gs.hw_heading:6.1f}°  {bearing}"
            hdg_clr  = (50, 220, 100)
        else:
            hdg_text = "  Heading:  ---  (fusion inactive)"
            hdg_clr  = (90, 90, 90)
        self._screen.blit(
            self._font_label.render(hdg_text, True, hdg_clr), (px + pad, y))
