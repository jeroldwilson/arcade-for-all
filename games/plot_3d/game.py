"""
plot_3d/game.py — Simple Scrib3D-style 3D Pen Plotter.

Treats the sensor on the child's wrist like the tip of a 3D printing pen:
  • Ignores static hand tilts (gravity is removed via sensor fusion)
  • Moving the wrist up/down (Z), left/right (X), and forward/back (Y)
    extrudes a dual-colored 3D filament ribbon
  • Supports live 6-axis (IMUPlus) vs 9-axis (NDoF) toggle with M
  • Cursor keys (← / → / ↑ / ↓) rotate the 3D camera, +/- or wheel zooms,
    F toggles fullscreen, SPACE / R clears & re-zeros at (0, 0, 0)
"""

from __future__ import annotations

import math
from collections import deque
from typing import Deque, Tuple

import pygame

from shared.quat import IDENTITY, Quat, q_conj, q_mul, q_normalize, q_rotate
from shared.sensor import StreamChannel

BG_TOP = (8, 12, 24)
GRID_CLR = (24, 34, 56)
AXIS_X_CLR = (125, 62, 68)
AXIS_Y_CLR = (60, 120, 82)
AXIS_Z_CLR = (62, 102, 145)
RIBBON_LEFT_CLR = (0, 240, 255)
RIBBON_RIGHT_CLR = (255, 75, 175)
SHADOW_CLR = (36, 54, 86)


class Plot3DGame:
    """Scrib3D-style 3D wrist-movement plotter with 6-axis/9-axis toggle."""

    def __init__(self, screen: pygame.Surface, clock: pygame.time.Clock,
                 debug: bool = False, mode: str = "standard",
                 audio=None, username: str = ""):
        self.screen = screen
        self.clock = clock
        self.debug = debug
        self._debug = debug
        self.mode = mode
        self.audio = audio
        self.username = username

        self._init_layout(screen)

        self.cam_yaw = 35.0
        self.cam_pitch = 24.0
        self.cam_zoom = 1.0

        self.trail: Deque[Tuple[float, float, float]] = deque(maxlen=500)
        self.cur_pos: Tuple[float, float, float] = (0.0, 0.0, 0.0)

        self._sf_mode = "imuplus"
        self._needs_rezero = True
        self._q_rest: Quat = IDENTITY
        self._pen_vel = [0.0, 0.0, 0.0]
        self._pen_pos = [0.0, 0.0, 0.0]
        self._lin_bias = [0.0, 0.0, 0.0]
        self._still_time = 0.0
        self._last_frame_t: float = -1.0
        self._kb_pos = [0.0, 0.0, 0.0]

    def _init_layout(self, screen: pygame.Surface) -> None:
        self.screen = screen
        self.W, self.H = screen.get_size()
        self.sc = min(self.W / 800.0, self.H / 600.0)
        self._is_fullscreen = not (self.W == 800 and self.H == 600)
        usable_h = max(200.0, self.H - 110.0 * self.sc)
        usable_w = max(200.0, self.W - 60.0 * self.sc)
        self._fit_scale = min(usable_w, usable_h) / 92.0
        if not pygame.font.get_init():
            pygame.font.init()
        try:
            self.font_title = pygame.font.SysFont("Arial", max(16, int(22 * self.sc)), bold=True)
            self.font_ui = pygame.font.SysFont("Arial", max(12, int(14 * self.sc)))
            self.font_small = pygame.font.SysFont("Arial", max(11, int(12 * self.sc)))
        except Exception:
            self.font_title = pygame.font.Font(None, max(20, int(26 * self.sc)))
            self.font_ui = pygame.font.Font(None, max(16, int(18 * self.sc)))
            self.font_small = pygame.font.Font(None, max(14, int(16 * self.sc)))

    def _toggle_fullscreen(self) -> None:
        self._is_fullscreen = not self._is_fullscreen
        if self._is_fullscreen:
            surf = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        else:
            surf = pygame.display.set_mode((800, 600))
        self._init_layout(surf)

    def _adjust_zoom(self, delta: float) -> None:
        self.cam_zoom = max(0.45, min(2.8, self.cam_zoom + delta))

    def _project(self, x: float, y: float, z: float) -> Tuple[int, int, float]:
        yr = math.radians(self.cam_yaw)
        pr = math.radians(self.cam_pitch)
        cy, sy = math.cos(yr), math.sin(yr)
        cp, sp = math.cos(pr), math.sin(pr)

        rx = x * cy - y * sy
        ry = x * sy + y * cy
        rz = z

        px = rx
        py = ry * cp - rz * sp
        pz = ry * sp + rz * cp

        cam_dist = 150.0
        scale = (cam_dist * self._fit_scale * self.cam_zoom) / max(40.0, cam_dist + py)
        sx = int(self.W * 0.5 + px * scale)
        sy_scr = int(self.H * 0.54 - pz * scale)
        return sx, sy_scr, py

    def _rezero(self, gs, gesture_src=None) -> None:
        self.trail.clear()
        self.cur_pos = (0.0, 0.0, 0.0)
        self._pen_vel = [0.0, 0.0, 0.0]
        self._pen_pos = [0.0, 0.0, 0.0]
        self._kb_pos = [0.0, 0.0, 0.0]
        self._still_time = 0.0
        buf = getattr(gesture_src, "buffer", None) if gesture_src is not None else None
        self._last_frame_t = buf[-1].t if buf else -1.0
        if gs is not None:
            self._q_rest = q_normalize((
                getattr(gs, "qw", 1.0),
                getattr(gs, "qx", 0.0),
                getattr(gs, "qy", 0.0),
                getattr(gs, "qz", 0.0),
            ))
            self._lin_bias = [
                float(getattr(gs, "lin_ax", 0.0)),
                float(getattr(gs, "lin_ay", 0.0)),
                float(getattr(gs, "lin_az", 0.0)),
            ]
        else:
            self._q_rest = IDENTITY
            self._lin_bias = [0.0, 0.0, 0.0]
        self._needs_rezero = False

    def _step_pen_tip(
        self,
        lax: float,
        lay: float,
        laz: float,
        q_now: Quat,
        dt: float,
    ) -> None:
        """Move 3D pen tip from gravity-removed linear acceleration (ignores hand tilts)."""
        dt = max(0.001, min(0.05, dt))
        cx = lax - self._lin_bias[0]
        cy = lay - self._lin_bias[1]
        cz = laz - self._lin_bias[2]

        q_rel = q_normalize(q_mul(q_now, q_conj(self._q_rest)))
        awx, awy, awz = q_rotate(q_rel, (cx, cy, cz))
        acc_mag = math.sqrt(awx * awx + awy * awy + awz * awz)

        if acc_mag < 0.06:
            self._still_time += dt
            if self._still_time >= 0.04:
                self._pen_vel = [0.0, 0.0, 0.0]
                for i, raw_v in enumerate((lax, lay, laz)):
                    self._lin_bias[i] = 0.95 * self._lin_bias[i] + 0.05 * raw_v
                return
        else:
            self._still_time = 0.0

        g_to_cm_s2 = 980.665
        damp = max(0.0, 1.0 - 6.0 * dt)
        dead = 0.045
        for i, a_g in enumerate((awx, awy, awz)):
            if abs(a_g) < dead:
                a_g = 0.0
            v = (self._pen_vel[i] + a_g * g_to_cm_s2 * dt) * damp
            v = max(-40.0, min(40.0, v))
            self._pen_vel[i] = v
            self._pen_pos[i] = max(-30.0, min(30.0, self._pen_pos[i] + v * dt))

    def _update_position(self, gs, sig, dt: float, gesture_src=None) -> None:
        keys = pygame.key.get_pressed()
        kb_speed = 25.0 * dt
        kb_moved = False
        if keys[pygame.K_a]:
            self._kb_pos[0] -= kb_speed; kb_moved = True
        if keys[pygame.K_d] and not (keys[pygame.K_LCTRL] or keys[pygame.K_RCTRL]):
            self._kb_pos[0] += kb_speed; kb_moved = True
        if keys[pygame.K_w]:
            self._kb_pos[1] += kb_speed; kb_moved = True
        if keys[pygame.K_s]:
            self._kb_pos[1] -= kb_speed; kb_moved = True
        if keys[pygame.K_e]:
            self._kb_pos[2] += kb_speed; kb_moved = True
        if keys[pygame.K_q]:
            self._kb_pos[2] -= kb_speed; kb_moved = True

        if kb_moved:
            self.cur_pos = (self._kb_pos[0], self._kb_pos[1], self._kb_pos[2])
        elif sig is not None and getattr(sig, "dual_sensor_active", False):
            self.cur_pos = (sig.pos_x, sig.pos_y, sig.pos_z)
        elif gs is not None and getattr(gs, "calibrated", False):
            q_w = q_normalize((
                getattr(gs, "qw", 1.0),
                getattr(gs, "qx", 0.0),
                getattr(gs, "qy", 0.0),
                getattr(gs, "qz", 0.0),
            ))
            if self._needs_rezero:
                self._rezero(gs, gesture_src)

            buf = getattr(gesture_src, "buffer", None) if gesture_src is not None else None
            new_frames = [f for f in list(buf) if f.t > self._last_frame_t] if buf else []
            if new_frames:
                for f in new_frames:
                    self._last_frame_t = f.t
                    self._step_pen_tip(f.lin_ax, f.lin_ay, f.lin_az, q_w, f.dt)
            else:
                self._step_pen_tip(
                    float(getattr(gs, "lin_ax", 0.0)),
                    float(getattr(gs, "lin_ay", 0.0)),
                    float(getattr(gs, "lin_az", 0.0)),
                    q_w,
                    dt,
                )
            self.cur_pos = (self._pen_pos[0], self._pen_pos[1], self._pen_pos[2])

        if (not self.trail
                or math.hypot(
                    self.cur_pos[0] - self.trail[-1][0],
                    self.cur_pos[1] - self.trail[-1][1],
                ) > 0.15
                or abs(self.cur_pos[2] - self.trail[-1][2]) > 0.15):
            self.trail.append(self.cur_pos)

    def _draw_scene(self, sig) -> None:
        self.screen.fill(BG_TOP)

        extent = 30
        step = 10
        for g in range(-extent, extent + 1, step):
            p1 = self._project(g, -extent, 0.0)
            p2 = self._project(g, extent, 0.0)
            pygame.draw.aaline(self.screen, GRID_CLR, p1[:2], p2[:2])
            p3 = self._project(-extent, g, 0.0)
            p4 = self._project(extent, g, 0.0)
            pygame.draw.aaline(self.screen, GRID_CLR, p3[:2], p4[:2])

        o = self._project(0.0, 0.0, 0.0)[:2]
        ax_x = self._project(28.0, 0.0, 0.0)[:2]
        ax_y = self._project(0.0, 28.0, 0.0)[:2]
        ax_z = self._project(0.0, 0.0, 28.0)[:2]
        pygame.draw.aaline(self.screen, AXIS_X_CLR, o, ax_x)
        pygame.draw.aaline(self.screen, AXIS_Y_CLR, o, ax_y)
        pygame.draw.aaline(self.screen, AXIS_Z_CLR, o, ax_z)
        self.screen.blit(self.font_small.render("+X", True, AXIS_X_CLR), ax_x)
        self.screen.blit(self.font_small.render("+Y", True, AXIS_Y_CLR), ax_y)
        self.screen.blit(self.font_small.render("+Z", True, AXIS_Z_CLR), ax_z)
        pygame.draw.circle(self.screen, (165, 180, 205), o, 4)

        pts = list(self.trail)
        if len(pts) >= 2:
            shadow_pts = [self._project(px, py, 0.0)[:2] for px, py, _ in pts]
            pygame.draw.aalines(self.screen, SHADOW_CLR, False, shadow_pts)

            left_edge, right_edge = [], []
            half_w = 0.85
            for i, (px, py, pz) in enumerate(pts):
                if i < len(pts) - 1:
                    tx, ty = pts[i + 1][0] - px, pts[i + 1][1] - py
                else:
                    tx, ty = px - pts[i - 1][0], py - pts[i - 1][1]
                mag = math.hypot(tx, ty)
                nx, ny = (-ty / mag, tx / mag) if mag >= 1e-4 else (1.0, 0.0)
                left_edge.append(self._project(px + nx * half_w, py + ny * half_w, pz)[:2])
                right_edge.append(self._project(px - nx * half_w, py - ny * half_w, pz)[:2])

            for i in range(len(pts) - 1):
                quad = [left_edge[i], left_edge[i + 1], right_edge[i + 1], right_edge[i]]
                pygame.draw.polygon(self.screen, (42, 68, 108), quad)
            pygame.draw.lines(self.screen, RIBBON_LEFT_CLR, False, left_edge, 2)
            pygame.draw.lines(self.screen, RIBBON_RIGHT_CLR, False, right_edge, 2)

        cur_scr = self._project(*self.cur_pos)[:2]
        cur_floor = self._project(self.cur_pos[0], self.cur_pos[1], 0.0)[:2]
        pygame.draw.aaline(self.screen, (140, 160, 200), cur_floor, cur_scr)
        pygame.draw.circle(self.screen, (255, 235, 90), cur_scr, max(5, int(7 * self.sc)))

        dual = bool(sig is not None and getattr(sig, "dual_sensor_active", False))
        mode_str = "DUAL SENSOR (2-Seg FK)" if dual else "SCRIB3D WRIST PEN"
        sf_label = "NDoF 9-Axis" if self._sf_mode == "ndof" else "IMUPlus 6-Axis"
        title_s = self.font_title.render(
            f"3D PLOTTER  —  {mode_str}  [{sf_label}]", True, (235, 245, 255)
        )
        self.screen.blit(title_s, (18, 14))

        pos_s = self.font_ui.render(
            f"Pen (cm): X={self.cur_pos[0]:+5.1f}  Y={self.cur_pos[1]:+5.1f}  Z={self.cur_pos[2]:+5.1f}   "
            f"|  Yaw={self.cam_yaw:.0f}° Pitch={self.cam_pitch:.0f}°  Zoom={int(self.cam_zoom * 100)}%",
            True, (165, 225, 255),
        )
        self.screen.blit(pos_s, (18, 44))

        help_s = self.font_small.render(
            "Arrows: Rotate  |  +/- or Wheel: Zoom  |  M: IMUPlus/NDoF  |  F: Fullscreen  |  SPACE/R: Clear  |  ESC: Home",
            True, (170, 185, 210),
        )
        self.screen.blit(help_s, (18, self.H - 28))

    def run(self, gesture_src) -> str:
        if gesture_src and hasattr(gesture_src, "set_detector_profile"):
            gesture_src.set_detector_profile(
                set(),
                washout_enabled=False,
                extra_channels=StreamChannel.DEFAULT_FULL,
            )

        sensor = getattr(gesture_src, "_sensor", None) if gesture_src else None
        if sensor is not None and hasattr(sensor, "sf_mode"):
            self._sf_mode = sensor.sf_mode

        self._needs_rezero = True
        dt = 0.016
        try:
            while True:
                cur = pygame.display.get_surface()
                if cur is not None and cur.get_size() != (self.W, self.H):
                    self._init_layout(cur)

                gs = gesture_src.get_state() if gesture_src else None
                sig = gesture_src.signals() if (gesture_src and hasattr(gesture_src, "signals")) else None

                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        return "quit"
                    elif event.type == pygame.KEYDOWN:
                        if event.key == pygame.K_ESCAPE:
                            return "home"
                        elif event.key in (pygame.K_SPACE, pygame.K_r):
                            self._rezero(gs, gesture_src)
                        elif event.key == pygame.K_m:
                            self._sf_mode = "ndof" if self._sf_mode == "imuplus" else "imuplus"
                            if sensor is not None and hasattr(sensor, "set_sf_mode"):
                                sensor.set_sf_mode(self._sf_mode)
                            self._rezero(gs, gesture_src)
                        elif event.key == pygame.K_f:
                            self._toggle_fullscreen()
                        elif event.key in (pygame.K_PLUS, pygame.K_EQUALS, pygame.K_KP_PLUS):
                            self._adjust_zoom(0.15)
                        elif event.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
                            self._adjust_zoom(-0.15)
                        elif event.key == pygame.K_d:
                            self.debug = not self.debug
                            self._debug = self.debug
                    elif event.type == pygame.MOUSEWHEEL:
                        self._adjust_zoom(event.y * 0.12)

                keys = pygame.key.get_pressed()
                if keys[pygame.K_LEFT]:
                    self.cam_yaw -= 90.0 * dt
                if keys[pygame.K_RIGHT]:
                    self.cam_yaw += 90.0 * dt
                if keys[pygame.K_UP]:
                    self.cam_pitch = min(85.0, self.cam_pitch + 75.0 * dt)
                if keys[pygame.K_DOWN]:
                    self.cam_pitch = max(-85.0, self.cam_pitch - 75.0 * dt)

                self._update_position(gs, sig, dt, gesture_src=gesture_src)
                self._draw_scene(sig)
                pygame.display.flip()
                dt = self.clock.tick(60) / 1000.0
        finally:
            if gesture_src and hasattr(gesture_src, "reset_profile"):
                gesture_src.reset_profile()
