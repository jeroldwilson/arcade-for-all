import pygame
import pygame.gfxdraw
import math
import time
from typing import Optional, Tuple, List
from shared.gesture import GestureState


class GestureHUD:
    """
    Renders a live, interactive 3D-perspective Realistic Right-Hand Avatar
    inside a translucent circular glass HUD.

    Dynamically tracks and visualizes:
      • Real-time 3D wrist roll & pitch (from Euler angles, raw accelerometer, or keyboard)
      • Mirror-mode tilt: user tilts left → on-screen hand tilts left (Kinect convention)
      • High-speed Gyro Flicks (Left / Right / Up / Down / Launch)
      • Twist / Spin rotation
      • Live gesture badges & continuous degree readouts
      • Pulsating MetaMotion BLE Sensor LED on the thumb-side (left) edge of the sensor pod
      • Right-hand anatomy: thumb on left side (back-of-hand / dorsal view)

    The sensor is worn on the RIGHT wrist with the green LED on the left (thumb-side)
    edge of the sensor pod, matching the physical MetaMotion band orientation.
    """

    # ── Skin, wristband & sensor color palette ───────────────────────────────
    _SKIN_LIGHT = (248, 206, 175)    # dorsal highlights
    _SKIN_BASE = (238, 190, 158)     # main skin
    _SKIN_SHADE = (215, 165, 130)    # shaded areas
    _SKIN_EDGE = (180, 130, 95)      # outlines / knuckle lines
    _NAIL_COLOR = (255, 225, 210)    # fingernails
    _NAIL_EDGE = (230, 195, 170)     # nail outline

    _BAND_MAIN = (42, 52, 78)        # dark navy band
    _BAND_ACCENT = (65, 85, 130)     # band highlight
    _BAND_EDGE = (28, 35, 55)        # band outline
    _SENSOR_BODY = (22, 22, 28)      # sensor pod body (matte black)
    _SENSOR_EDGE = (75, 75, 90)      # sensor pod outline
    _SENSOR_FACE = (35, 35, 45)      # sensor pod face (slightly lighter)
    _SENSOR_FACE_BORDER = (55, 55, 65)

    # ── Static 3D right-hand geometry (dorsal / back-of-hand view) ───────────
    # Y-axis: negative = toward fingertips, positive = toward forearm
    # X-axis: negative = thumb side (left on screen), positive = pinky side
    _FOREARM_3D = (
        (-14, 42, 2), (14, 42, 2), (16, 56, 8), (-16, 56, 8),
    )
    _WRIST_3D = (
        (-15, 30, 1), (15, 30, 1), (14, 44, 3), (-14, 44, 3),
    )
    # Convex perimeter ordered clockwise: top-left → top-right → right side → bottom → left side
    _PALM_3D = (
        (-16, -3, 1), (15, -3, 1),
        (17, 2, 0), (16, 10, 1),
        (15, 22, 2), (-16, 22, 2),
        (-17, 10, 1), (-19, 2, 0),
    )
    _BAND_3D = (
        (-17, 26, -2), (17, 26, -2), (16, 38, 4), (-16, 38, 4),
    )
    _BAND_MID_3D = (
        (-16.5, 31, -1), (16.5, 31, -1), (16, 33, 1), (-16, 33, 1),
    )
    _BAND_DOTS_3D = (
        (-12, 30, -1), (-6, 30, -1), (0, 30, -1), (6, 30, -1), (12, 30, -1),
        (-9, 35, 2), (-3, 35, 2), (3, 35, 2), (9, 35, 2),
    )
    _SENSOR_3D = (
        (-11, 28, -7), (11, 28, -7), (10, 37, -5), (-10, 37, -5),
    )
    _SENSOR_FACE_3D = (
        (-9, 29, -8), (9, 29, -8), (8, 36, -6), (-8, 36, -6),
    )
    _KNUCKLE_RIDGE_3D = (
        (-14, -2, 0.5), (-7, -4, 0.5), (0, -4, 0.5),
        (7, -3.5, 0.5), (14, -2, 0.5),
    )

    # Each entry: (base_poly, mid_poly, tip_poly, tip_pos, nail_pos, knuckles, is_thumb)
    _FINGERS_3D = (
        # Thumb (left side, angled outward)
        (
            ((-18, 3, 1), (-22, -2, 2), (-28, -8, 3), (-24, -12, 2)),
            ((-24, -12, 2), (-28, -8, 3), (-32, -16, 4), (-28, -20, 3)),
            None,
            (-30, -18, 3.5),
            (-30, -19, 3),
            ((-25, -10, 2.5),),
            True,
        ),
        # Index finger
        (
            ((-14, -3, 1), (-12, -20, 2), (-7, -20, 2), (-7, -3, 1)),
            ((-12, -20, 2), (-11, -32, 3), (-8, -32, 3), (-7, -20, 2)),
            ((-11, -32, 3), (-10.5, -40, 4), (-8.5, -40, 4), (-8, -32, 3)),
            (-9.5, -40, 4),
            (-9.5, -39, 3.5),
            ((-10, -3, 1), (-10, -20, 2.5)),
            False,
        ),
        # Middle finger (longest)
        (
            ((-6, -3, 1), (-5, -22, 2), (0, -22, 2), (0, -3, 1)),
            ((-5, -22, 2), (-4.5, -36, 3), (-0.5, -36, 3), (0, -22, 2)),
            ((-4.5, -36, 3), (-4, -46, 5), (-1, -46, 5), (-0.5, -36, 3)),
            (-2.5, -46, 5),
            (-2.5, -45, 4.5),
            ((-3, -3, 1), (-3, -22, 2.5)),
            False,
        ),
        # Ring finger
        (
            ((1, -3, 1), (2, -20, 2), (7, -20, 2), (7, -3, 1)),
            ((2, -20, 2), (2.5, -33, 3), (6.5, -33, 3), (7, -20, 2)),
            ((2.5, -33, 3), (3, -42, 4), (6, -42, 4), (6.5, -33, 3)),
            (4.5, -42, 4),
            (4.5, -41, 3.5),
            ((4, -3, 1), (4.5, -20, 2.5)),
            False,
        ),
        # Pinky finger (shortest, right side)
        (
            ((8, -2, 1), (9, -16, 2), (14, -16, 2), (14, -2, 1)),
            ((9, -16, 2), (10, -26, 3), (13, -26, 3), (14, -16, 2)),
            ((10, -26, 3), (10.5, -33, 3), (12.5, -33, 3), (13, -26, 3)),
            (11.5, -33, 3),
            (11.5, -32, 2.5),
            ((11, -2, 1), (11.5, -16, 2.5)),
            False,
        ),
    )

    def __init__(self, image_path: Optional[str] = None, scale: float = 0.3):
        # `image_path` is retained for backward compatibility with existing callers.
        _ = image_path
        self.scale = scale
        scale_ratio = scale / 0.3 if scale > 0 else 1.0
        self._hud_r = max(32, int(round(92 * scale_ratio)))
        self._geom_scale = 1.55 * scale_ratio

        # Smooth interpolation state
        self.current_roll = 0.0       # degrees
        self.current_pitch = 0.0      # degrees
        self.current_offset_x = 0.0   # pixels (flick nudge)
        self.current_offset_y = 0.0   # pixels (flick nudge)
        self.launch_anim = 0.0        # spring lift for flick-up

        self.flick_cooldown = 0.0

        # Badge state
        self.active_gesture_text = ""
        self.active_gesture_color = (255, 255, 255)
        self.gesture_timer = 0.0

        if not pygame.font.get_init():
            pygame.font.init()
        self.font_badge = pygame.font.SysFont("Arial", 15, bold=True)
        self.font_val = pygame.font.SysFont("Arial", 12, bold=True)

        # Pre-render static glass HUD pod and reusable LED surface
        self._hc = self._hud_r + 6
        self._base_hud_surf = self._build_base_hud_surface()
        self._arc_hud_surf = pygame.Surface(self._base_hud_surf.get_size(), pygame.SRCALPHA)
        max_glow_r = 9
        self._led_surf_half = max_glow_r * 2 + 4
        self._led_surf = pygame.Surface(
            (self._led_surf_half * 2, self._led_surf_half * 2), pygame.SRCALPHA
        )

    # ── Private helpers ───────────────────────────────────────────────────────

    def _build_base_hud_surface(self) -> pygame.Surface:
        """Pre-render the static translucent glass pod and crosshair once."""
        hud_r = self._hud_r
        hc_x = hc_y = self._hc
        surf = pygame.Surface((hud_r * 2 + 12, hud_r * 2 + 12), pygame.SRCALPHA)

        # Glassmorphic pod: layered circles for depth
        self._aa_circle(surf, (15, 22, 38, 185), hc_x, hc_y, hud_r)
        self._aa_circle(surf, (35, 55, 90, 150), hc_x, hc_y, hud_r - 2)
        # Outer rim glow
        try:
            pygame.gfxdraw.aacircle(surf, hc_x, hc_y, hud_r, (80, 150, 235, 210))
            pygame.gfxdraw.aacircle(surf, hc_x, hc_y, hud_r - 1, (60, 120, 200, 140))
        except (ValueError, OverflowError):
            pygame.draw.circle(surf, (80, 150, 235, 210), (hc_x, hc_y), hud_r, 2)

        # Fine crosshair
        pygame.draw.line(
            surf, (60, 80, 120, 70),
            (hc_x - hud_r + 14, hc_y), (hc_x + hud_r - 14, hc_y), 1,
        )
        pygame.draw.line(
            surf, (60, 80, 120, 70),
            (hc_x, hc_y - hud_r + 14), (hc_x, hc_y + hud_r - 14), 1,
        )
        return surf

    def _trigger_gesture(self, text: str, color: Tuple[int, int, int], duration: float = 0.55):
        self.active_gesture_text = text
        self.active_gesture_color = color
        self.gesture_timer = duration

    def _project_3d(
        self,
        x: float, y: float, z: float,
        roll_rad: float, pitch_rad: float,
        cx: float, cy: float,
        fov: float = 200.0,
    ) -> Tuple[int, int]:
        """Rotate point (x,y,z) in 3D by roll and pitch, then perspective-project to 2D."""
        # 1. Pitch around X-axis
        y1 = y * math.cos(pitch_rad) - z * math.sin(pitch_rad)
        z1 = y * math.sin(pitch_rad) + z * math.cos(pitch_rad)
        x1 = x

        # 2. Roll around Z-axis
        x2 = x1 * math.cos(roll_rad) - y1 * math.sin(roll_rad)
        y2 = x1 * math.sin(roll_rad) + y1 * math.cos(roll_rad)
        z2 = z1

        # 3. Perspective projection
        depth = fov / (fov + z2 + 80.0)
        proj_x = cx + x2 * depth
        proj_y = cy + y2 * depth
        return int(proj_x), int(proj_y)

    def _aa_polygon(self, surface: pygame.Surface, color: Tuple[int, ...], points: List[Tuple[int, int]]):
        """Draw an antialiased filled polygon using gfxdraw."""
        if len(points) < 3:
            return
        try:
            pygame.gfxdraw.filled_polygon(surface, points, color)
            pygame.gfxdraw.aapolygon(surface, points, color)
        except (ValueError, OverflowError):
            # Fallback if points are degenerate
            pygame.draw.polygon(surface, color[:3], points)

    def _aa_circle(self, surface: pygame.Surface, color: Tuple[int, ...], cx: int, cy: int, r: int):
        """Draw an antialiased filled circle using gfxdraw."""
        if r < 1:
            r = 1
        try:
            pygame.gfxdraw.filled_circle(surface, cx, cy, r, color)
            pygame.gfxdraw.aacircle(surface, cx, cy, r, color)
        except (ValueError, OverflowError):
            pygame.draw.circle(surface, color[:3], (cx, cy), r)

    def _aa_ellipse(self, surface: pygame.Surface, color: Tuple[int, ...], cx: int, cy: int, rx: int, ry: int):
        """Draw an antialiased filled ellipse."""
        if rx < 1:
            rx = 1
        if ry < 1:
            ry = 1
        try:
            pygame.gfxdraw.filled_ellipse(surface, cx, cy, rx, ry, color)
            pygame.gfxdraw.aaellipse(surface, cx, cy, rx, ry, color)
        except (ValueError, OverflowError):
            rect = pygame.Rect(cx - rx, cy - ry, rx * 2, ry * 2)
            pygame.draw.ellipse(surface, color[:3], rect)

    # ── Main draw ─────────────────────────────────────────────────────────────

    def draw(self, screen: pygame.Surface, gs: GestureState, x: int, y: int):
        if gs is None:
            return

        dt = 0.016
        if self.flick_cooldown > 0:
            self.flick_cooldown -= dt

        # ── 1. COMPUTE TARGET ORIENTATION ─────────────────────────────────────
        # Mirror mode (Kinect convention):
        #   Physical tilt left  → euler_roll < 0 → target_roll > 0 → screen hand tilts left  ✓
        #   Physical tilt right → euler_roll > 0 → target_roll < 0 → screen hand tilts right ✓
        target_roll = 0.0
        target_pitch = 0.0

        if hasattr(gs, 'euler_roll') and abs(gs.euler_roll) > 1.0:
            target_roll = -gs.euler_roll * 0.95
        elif hasattr(gs, 'raw_ax') and abs(gs.raw_ax) > 0.02:
            target_roll = -gs.raw_ax * 75.0
        elif hasattr(gs, 'paddle_velocity') and abs(gs.paddle_velocity) > 0.05:
            target_roll = -gs.paddle_velocity * 45.0

        if hasattr(gs, 'euler_pitch') and abs(gs.euler_pitch) > 1.0:
            target_pitch = gs.euler_pitch * 0.8
        elif hasattr(gs, 'tilt_y') and abs(gs.tilt_y) > 0.05:
            target_pitch = gs.tilt_y * 40.0

        # Keyboard mirror-mode
        keys = pygame.key.get_pressed()
        if keys[pygame.K_LEFT]:
            target_roll = 35.0       # left key → hand tilts left on screen
        elif keys[pygame.K_RIGHT]:
            target_roll = -35.0      # right key → hand tilts right on screen
        if keys[pygame.K_UP]:
            target_pitch = -25.0
        elif keys[pygame.K_DOWN]:
            target_pitch = 25.0

        # ── 2. FLICK / GESTURE DETECTION ───────────────────────────────────────
        gx = getattr(gs, 'abs_gx', 0.0)
        gy = getattr(gs, 'abs_gy', 0.0)
        gz = getattr(gs, 'abs_gz', 0.0)

        if gs.launch or ((keys[pygame.K_SPACE] or gy > 140.0) and self.flick_cooldown <= 0):
            self._trigger_gesture("LAUNCH / FLICK UP!", (255, 230, 80), 0.7)
            self.launch_anim = 1.0
            self.flick_cooldown = 0.4
        elif gs.steer_left or ((gx < -110.0 or gz < -110.0) and self.flick_cooldown <= 0):
            self._trigger_gesture("FLICK LEFT", (80, 255, 140), 0.6)
            self.current_offset_x = -38.0
            self.flick_cooldown = 0.35
        elif gs.steer_right or ((gx > 110.0 or gz > 110.0) and self.flick_cooldown <= 0):
            self._trigger_gesture("FLICK RIGHT", (80, 255, 140), 0.6)
            self.current_offset_x = 38.0
            self.flick_cooldown = 0.35
        elif gs.steer_down or (gy < -130.0 and self.flick_cooldown <= 0):
            self._trigger_gesture("FLICK DOWN", (100, 220, 255), 0.6)
            self.current_offset_y = 30.0
            self.flick_cooldown = 0.35
        elif getattr(gs, 'slice_active', False) and getattr(gs, 'slice_direction', ''):
            if abs(gz) > 100.0 or abs(gy) > 100.0 or abs(gx) > 100.0:
                self._trigger_gesture(f"SLICE {gs.slice_direction.upper()}", (255, 110, 100), 0.45)
        elif abs(target_roll) > 10.0:
            direction = "TILT LEFT" if target_roll > 0 else "TILT RIGHT"
            self._trigger_gesture(f"{direction} {int(abs(target_roll))}°", (140, 215, 255), 0.2)
        elif abs(target_pitch) > 12.0:
            direction = "TILT FORWARD" if target_pitch < 0 else "TILT BACK"
            self._trigger_gesture(direction, (140, 215, 255), 0.2)

        # ── 3. SMOOTH PHYSICS / SPRING INTERPOLATION ──────────────────────────
        self.current_roll += (target_roll - self.current_roll) * 0.35
        self.current_pitch += (target_pitch - self.current_pitch) * 0.35
        self.current_offset_x += (0.0 - self.current_offset_x) * 0.16
        self.current_offset_y += (0.0 - self.current_offset_y) * 0.16
        self.launch_anim += (0.0 - self.launch_anim) * 0.14

        roll_rad = math.radians(self.current_roll)
        pitch_rad = math.radians(self.current_pitch - (self.launch_anim * 30.0))

        # ── 4. GLASS HUD BACKGROUND ──────────────────────────────────────────
        hud_r = self._hud_r
        hc_x = hc_y = self._hc
        center_x = x
        center_y = y

        angle_rad = -roll_rad
        if abs(angle_rad) > 0.05:
            # Reset to cached base HUD surface and draw only the animated tilt arc
            self._arc_hud_surf.fill((0, 0, 0, 0))
            self._arc_hud_surf.blit(self._base_hud_surf, (0, 0))
            arc_rect = pygame.Rect(
                hc_x - hud_r + 5, hc_y - hud_r + 5,
                (hud_r - 5) * 2, (hud_r - 5) * 2,
            )
            start_a = math.pi / 2 - max(0.0, angle_rad)
            end_a = math.pi / 2 - min(0.0, angle_rad)
            arc_color = (80, 230, 255, 240) if abs(angle_rad) < 0.6 else (255, 200, 70, 240)
            pygame.draw.arc(
                self._arc_hud_surf, arc_color, arc_rect,
                min(start_a, end_a), max(start_a, end_a), 4,
            )
            screen.blit(self._arc_hud_surf, (center_x - hc_x, center_y - hc_y))
        else:
            screen.blit(self._base_hud_surf, (center_x - hc_x, center_y - hc_y))

        # ── 5. REALISTIC 3D RIGHT-HAND AVATAR ────────────────────────────────
        hx = center_x + self.current_offset_x
        hy = center_y + self.current_offset_y - (self.launch_anim * 40.0)

        sc = self._geom_scale

        def proj(px, py, pz):
            return self._project_3d(px * sc, py * sc, pz * sc, roll_rad, pitch_rad, hx, hy)

        def proj_poly(poly):
            return [proj(px, py, pz) for px, py, pz in poly]

        # ─── DRAW ORDER (back to front) ──────────────────────────────────

        # 1. Forearm
        pts = proj_poly(self._FOREARM_3D)
        self._aa_polygon(screen, self._SKIN_SHADE, pts)

        # 2. Wrist
        pts = proj_poly(self._WRIST_3D)
        self._aa_polygon(screen, self._SKIN_SHADE, pts)

        # 3. Palm body
        pts = proj_poly(self._PALM_3D)
        self._aa_polygon(screen, self._SKIN_BASE, pts)

        # 4. Fingers — each finger: base → mid → tip → rounded tip circle → nail → knuckle dots
        for base, mid, tip, tip_pos, nail_pos_3d, knuckle_list, is_thumb in self._FINGERS_3D:
            # Base phalanx
            pts = proj_poly(base)
            self._aa_polygon(screen, self._SKIN_BASE, pts)

            # Middle phalanx
            pts = proj_poly(mid)
            color = self._SKIN_LIGHT if not is_thumb else self._SKIN_BASE
            self._aa_polygon(screen, color, pts)

            # Tip phalanx (not for thumb — thumb has 2 segments)
            if tip is not None:
                pts = proj_poly(tip)
                self._aa_polygon(screen, self._SKIN_LIGHT, pts)

            # Rounded fingertip circle
            tp = proj(tip_pos[0], tip_pos[1], tip_pos[2])
            tip_r = 4 if not is_thumb else 5
            self._aa_circle(screen, self._SKIN_LIGHT, tp[0], tp[1], tip_r)

            # Fingernail (small lighter oval near the tip)
            np = proj(nail_pos_3d[0], nail_pos_3d[1], nail_pos_3d[2])
            nail_rx = 3 if not is_thumb else 4
            nail_ry = 4 if not is_thumb else 5
            self._aa_ellipse(screen, self._NAIL_COLOR, np[0], np[1], nail_rx, nail_ry)
            # Nail cuticle outline (subtle)
            try:
                pygame.gfxdraw.aaellipse(screen, np[0], np[1], nail_rx, nail_ry, self._NAIL_EDGE)
            except (ValueError, OverflowError):
                pass

            # Knuckle dots (small circles at joint creases)
            for kx, ky, kz in knuckle_list:
                kp = proj(kx, ky, kz)
                self._aa_circle(screen, self._SKIN_EDGE, kp[0], kp[1], 2)

        # 5. Knuckle line across top of palm (metacarpal ridge)
        kr_pts = [proj(kx, ky, kz) for kx, ky, kz in self._KNUCKLE_RIDGE_3D]
        for i in range(len(kr_pts) - 1):
            pygame.draw.aaline(screen, self._SKIN_EDGE, kr_pts[i], kr_pts[i + 1])

        # 6. Wristband (wraps around the wrist)
        pts_band = proj_poly(self._BAND_3D)
        self._aa_polygon(screen, self._BAND_MAIN, pts_band)
        # Band accent stripe (subtle lighter line in the middle)
        pts_mid = proj_poly(self._BAND_MID_3D)
        self._aa_polygon(screen, self._BAND_ACCENT, pts_mid)
        # Band edge outline
        for i in range(len(pts_band)):
            pygame.draw.aaline(screen, self._BAND_EDGE, pts_band[i], pts_band[(i + 1) % len(pts_band)])

        # Band texture dots (small fabric-like pattern)
        for dx, dy, dz in self._BAND_DOTS_3D:
            dp = proj(dx, dy, dz)
            self._aa_circle(screen, self._BAND_ACCENT, dp[0], dp[1], 1)

        # 7. Sensor pod (MetaMotion — sits on dorsal side of band)
        pts_sensor = proj_poly(self._SENSOR_3D)
        self._aa_polygon(screen, self._SENSOR_BODY, pts_sensor)
        # Sensor pod outline
        for i in range(len(pts_sensor)):
            pygame.draw.aaline(screen, self._SENSOR_EDGE, pts_sensor[i], pts_sensor[(i + 1) % len(pts_sensor)])
        # Sensor face (recessed glass-like surface)
        pts_face = proj_poly(self._SENSOR_FACE_3D)
        self._aa_polygon(screen, self._SENSOR_FACE, pts_face)
        # Sensor face subtle border
        for i in range(len(pts_face)):
            pygame.draw.aaline(screen, self._SENSOR_FACE_BORDER, pts_face[i], pts_face[(i + 1) % len(pts_face)])

        # 8. Glowing MetaMotion LED — positioned on the LEFT side of the sensor pod
        # When worn on right wrist, LED faces toward the thumb side (negative X).
        # X = -10 (left edge of sensor), Y = 32.5 (vertically centered), Z = -7 (surface)
        led_center = proj(-10, 32.5, -7)
        led_color = (100, 255, 120) if getattr(gs, "calibrated", True) else (255, 160, 40)
        pulse = (math.sin(time.time() * 6.0) + 1.0) * 0.5

        # Multi-layer glow for realism on reusable surface
        glow_r = int(6 + pulse * 3)
        lc = self._led_surf_half
        self._led_surf.fill((0, 0, 0, 0))
        # Outer glow halo
        self._aa_circle(self._led_surf, (*led_color[:3], 30), lc, lc, glow_r + 2)
        # Middle glow
        self._aa_circle(self._led_surf, (*led_color[:3], 70), lc, lc, glow_r - 1)
        # Inner bright core
        self._aa_circle(self._led_surf, (*led_color[:3], 200), lc, lc, max(2, glow_r - 3))
        # Hot center dot
        bright = tuple(min(255, c + 80) for c in led_color[:3])
        self._aa_circle(self._led_surf, (*bright, 255), lc, lc, 2)

        screen.blit(self._led_surf, (led_center[0] - lc, led_center[1] - lc))

        # ── 6. GESTURE BADGES & ANGLE READOUT ────────────────────────────────
        if self.gesture_timer > 0:
            self.gesture_timer -= dt
            badge_text = self.font_badge.render(self.active_gesture_text, True, self.active_gesture_color)
            bw, bh = badge_text.get_size()

            badge_bg = pygame.Surface((bw + 18, bh + 8), pygame.SRCALPHA)
            badge_bg.fill((15, 20, 32, 235))
            pygame.draw.rect(badge_bg, (*self.active_gesture_color, 220),
                             (0, 0, bw + 18, bh + 8), 1, border_radius=6)

            bx = center_x - (bw + 18) // 2
            by = center_y - hud_r - bh - 8
            screen.blit(badge_bg, (bx, by))
            screen.blit(badge_text, (bx + 9, by + 4))
        else:
            deg_val = int(self.current_roll)
            deg_str = f"{deg_val:+d}°" if abs(deg_val) > 1 else "READY"
            val_surf = self.font_val.render(deg_str, True, (140, 180, 225))
            screen.blit(val_surf, val_surf.get_rect(center=(center_x, center_y + hud_r - 14)))
